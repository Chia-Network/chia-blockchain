import asyncio
import json
import logging
import socket
import sys
import time
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Union, Any

from blspy import PrivateKey, AugSchemeMPL
from packaging.version import Version
from chia.consensus.constants import ConsensusConstants
from chia.consensus.pot_iterations import calculate_iterations_quality, is_overflow_block, calculate_sp_interval_iters
from chia.daemon.keychain_proxy import (
    KeychainProxyConnectionFailure,
    connect_to_keychain_and_validate,
    wrap_local_keychain,
    KeychainProxy,
    KeyringIsEmpty,
)
from chia.full_node.weight_proof import WeightProofHandler
from chia.pools.pool_puzzles import SINGLETON_LAUNCHER_HASH, solution_to_pool_state
from chia.pools.pool_wallet import PoolWallet
from chia.protocols import wallet_protocol
from chia.protocols.full_node_protocol import RequestProofOfWeight, RespondProofOfWeight, RequestBlocks, RespondBlocks
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import (
    RespondToCoinUpdates,
    CoinState,
    RespondToPhUpdates,
    RespondBlockHeader,
    RequestAdditions,
    RespondAdditions,
    RejectAdditionsRequest,
    RequestSESInfo,
    RespondSESInfo,
    RespondRemovals,
    RejectRemovalsRequest,
)
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin, hash_coin_list
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.types.weight_proof import WeightProof, SubEpochData
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32, uint64
from chia.util.keychain import KeyringIsLocked
from chia.util.merkle_set import confirm_included_already_hashed, confirm_not_included_already_hashed, MerkleSet
from chia.util.path import mkdir, path_from_root
from chia.wallet.block_record import HeaderBlockRecord
from chia.wallet.derivation_record import DerivationRecord

from chia.wallet.settings.settings_objects import BackupInitialized
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.backup_utils import open_backup_file
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_action import WalletAction
from chia.util.profiler import profile_task


class PeerRequestCache:
    blocks: Dict[uint32, FullBlock]
    request_blocks: Dict[bytes32, Any]
    ses_requests: Dict[bytes32, Any]
    states_validated: Dict[bytes32, CoinState]

    def __init__(self):
        self.blocks = {}
        self.ses_requests = {}
        self.block_requests = {}
        self.states_validated = {}


class WalletNode:
    key_config: Dict
    config: Dict
    constants: ConsensusConstants
    server: Optional[ChiaServer]
    log: logging.Logger
    # Maintains the state of the wallet (blockchain and transactions), handles DB connections
    wallet_state_manager: Optional[WalletStateManager]
    _shut_down: bool
    root_path: Path
    state_changed_callback: Optional[Callable]
    syncing: bool
    full_node_peer: Optional[PeerInfo]
    peer_task: Optional[asyncio.Task]
    logged_in: bool
    wallet_peers_initialized: bool
    keychain_proxy: Optional[KeychainProxy]
    weight_proof_handler: WeightProofHandler

    def __init__(
        self,
        config: Dict,
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = None,
        local_keychain=None,
    ):
        self.config = config
        self.constants = consensus_constants
        self.root_path = root_path
        self.log = logging.getLogger(name if name else __name__)
        # Normal operation data
        self.cached_blocks: Dict = {}
        self.future_block_hashes: Dict = {}

        # Sync data
        self._shut_down = False
        self.proof_hashes: List = []
        self.state_changed_callback = None
        self.wallet_state_manager = None
        self.backup_initialized = False  # Delay first launch sync after user imports backup info or decides to skip
        self.server = None
        self.wsm_close_task = None
        self.sync_task: Optional[asyncio.Task] = None
        self.logged_in_fingerprint: Optional[int] = None
        self.peer_task = None
        self.logged_in = False
        self.keychain_proxy = None
        self.local_keychain = local_keychain
        self.height_to_time: Dict[uint32, uint64] = {}
        self.synced_peers: Set[bytes32] = set()

    async def ensure_keychain_proxy(self) -> KeychainProxy:
        if not self.keychain_proxy:
            if self.local_keychain:
                self.keychain_proxy = wrap_local_keychain(self.local_keychain, log=self.log)
            else:
                self.keychain_proxy = await connect_to_keychain_and_validate(self.root_path, self.log)
                if not self.keychain_proxy:
                    raise KeychainProxyConnectionFailure("Failed to connect to keychain service")
        return self.keychain_proxy

    async def get_key_for_fingerprint(self, fingerprint: Optional[int]) -> Optional[PrivateKey]:
        key: PrivateKey = None
        try:
            keychain_proxy = await self.ensure_keychain_proxy()
            key = await keychain_proxy.get_key_for_fingerprint(fingerprint)
        except KeyringIsEmpty:
            self.log.warning("No keys present. Create keys with the UI, or with the 'chia keys' program.")
            return None
        except KeyringIsLocked:
            self.log.warning("Keyring is locked")
            return None
        except KeychainProxyConnectionFailure as e:
            tb = traceback.format_exc()
            self.log.error(f"Missing keychain_proxy: {e} {tb}")
            raise e  # Re-raise so that the caller can decide whether to continue or abort
        return key

    async def _start(
        self,
        fingerprint: Optional[int] = None,
        new_wallet: bool = False,
        backup_file: Optional[Path] = None,
        skip_backup_import: bool = False,
    ) -> bool:
        private_key = await self.get_key_for_fingerprint(fingerprint)
        if private_key is None:
            self.logged_in = False
            return False

        if self.config.get("enable_profiler", False):
            asyncio.create_task(profile_task(self.root_path, "wallet", self.log))

        db_path_key_suffix = str(private_key.get_g1().get_fingerprint())
        db_path_replaced: str = (
            self.config["database_path"]
            .replace("CHALLENGE", self.config["selected_network"])
            .replace("KEY", db_path_key_suffix)
        )
        path = path_from_root(self.root_path, f"{db_path_replaced}_new")
        mkdir(path.parent)
        self.new_peak_lock = asyncio.Lock()
        assert self.server is not None
        self.wallet_state_manager = await WalletStateManager.create(
            private_key,
            self.config,
            path,
            self.constants,
            self.server,
            self.root_path,
            self.new_puzzle_hash_created,
            self.get_coin_state,
            self.subscribe_to_coin_updates,
            self,
        )

        self.wsm_close_task = None

        assert self.wallet_state_manager is not None

        backup_settings: BackupInitialized = self.wallet_state_manager.user_settings.get_backup_settings()
        if backup_settings.user_initialized is False:
            if new_wallet is True:
                await self.wallet_state_manager.user_settings.user_created_new_wallet()
                self.wallet_state_manager.new_wallet = True
            elif skip_backup_import is True:
                await self.wallet_state_manager.user_settings.user_skipped_backup_import()
            elif backup_file is not None:
                await self.wallet_state_manager.import_backup_info(backup_file)
            else:
                self.backup_initialized = False
                await self.wallet_state_manager.close_all_stores()
                self.wallet_state_manager = None
                self.logged_in = False
                return False

        self.backup_initialized = True

        if backup_file is not None:
            json_dict = open_backup_file(backup_file, self.wallet_state_manager.private_key)
            if "start_height" in json_dict["data"]:
                start_height = json_dict["data"]["start_height"]
                self.config["starting_height"] = max(0, start_height - self.config["start_height_buffer"])
            else:
                self.config["starting_height"] = 0
        else:
            self.config["starting_height"] = 0

        if self.state_changed_callback is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)

        self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)
        self._shut_down = False

        self.peer_task = asyncio.create_task(self._periodically_check_full_node())
        self.sync_event = asyncio.Event()
        self.logged_in_fingerprint = fingerprint
        self.logged_in = True
        return True

    async def new_puzzle_hash_created(self, puzzle_hashes):
        full_nodes = self.server.connection_by_type[NodeType.FULL_NODE]
        if len(full_nodes) > 0:
            full_node = list(full_nodes.values())[0]
            await self.subscribe_to_phs(puzzle_hashes, full_node)

    def _close(self):
        self.log.info("self._close")
        self.logged_in_fingerprint = None
        self._shut_down = True

    async def _await_closed(self):
        self.log.info("self._await_closed")
        await self.server.close_all_connections()
        if self.wallet_state_manager is not None:
            await self.wallet_state_manager.close_all_stores()
            self.wallet_state_manager = None
        self.logged_in = False

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

        if self.wallet_state_manager is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)
            self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)

    def _pending_tx_handler(self):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return None
        asyncio.create_task(self._resend_queue())

    async def _action_messages(self) -> List[Message]:
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return []
        actions: List[WalletAction] = await self.wallet_state_manager.action_store.get_all_pending_actions()
        result: List[Message] = []
        for action in actions:
            data = json.loads(action.data)
            action_data = data["data"]["action_data"]
            if action.name == "request_puzzle_solution":
                coin_name = bytes32(hexstr_to_bytes(action_data["coin_name"]))
                height = uint32(action_data["height"])
                msg = make_msg(
                    ProtocolMessageTypes.request_puzzle_solution,
                    wallet_protocol.RequestPuzzleSolution(coin_name, height),
                )
                result.append(msg)

        return result

    async def _resend_queue(self):
        if (
            self._shut_down
            or self.server is None
            or self.wallet_state_manager is None
            or self.backup_initialized is None
        ):
            return None

        for msg, sent_peers in await self._messages_to_resend():
            if (
                self._shut_down
                or self.server is None
                or self.wallet_state_manager is None
                or self.backup_initialized is None
            ):
                return None
            full_nodes = self.server.get_full_node_connections()
            for peer in full_nodes:
                if peer.peer_node_id in sent_peers:
                    continue
                await peer.send_message(msg)

        for msg in await self._action_messages():
            if (
                self._shut_down
                or self.server is None
                or self.wallet_state_manager is None
                or self.backup_initialized is None
            ):
                return None
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

    async def _messages_to_resend(self) -> List[Tuple[Message, Set[bytes32]]]:
        if self.wallet_state_manager is None or self.backup_initialized is False or self._shut_down:
            return []
        messages: List[Tuple[Message, Set[bytes32]]] = []

        records: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_not_sent()

        for record in records:
            if record.spend_bundle is None:
                continue
            msg = make_msg(
                ProtocolMessageTypes.send_transaction,
                wallet_protocol.SendTransaction(record.spend_bundle),
            )
            already_sent = set()
            for peer, status, _ in record.sent_to:
                if status == MempoolInclusionStatus.SUCCESS.value:
                    already_sent.add(hexstr_to_bytes(peer))
            messages.append((msg, already_sent))

        return messages

    def set_server(self, server: ChiaServer):
        self.server = server
        server.on_connect = self.on_connect

    async def on_connect(self, peer: WSChiaConnection):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return None

        if Version(peer.version) < Version("0.0.33"):
            self.log.info(f"Disconnecting, full node running old software")
            await peer.close()

        messages_peer_ids = await self._messages_to_resend()
        self.wallet_state_manager.state_changed("add_connection")
        for msg, peer_ids in messages_peer_ids:
            if peer.peer_node_id in peer_ids:
                continue
            await peer.send_message(msg)

    async def update_coin_state(self, full_node: WSChiaConnection):
        assert self.wallet_state_manager is not None
        self.wallet_state_manager.set_sync_mode(True)
        start_time = time.time()
        all_puzzle_hashes = list(await self.wallet_state_manager.puzzle_store.get_all_puzzle_hashes())
        current_height = await self.wallet_state_manager.blockchain.get_synced_height()
        request_height = uint32(max(0, current_height - 1000))
        await self.subscribe_to_phs(all_puzzle_hashes, full_node, request_height)
        all_coins = await self.wallet_state_manager.coin_store.get_coins_to_check(request_height)
        all_coin_names = [coin_record.name() for coin_record in all_coins]
        removed_dict, added_dict = await self.wallet_state_manager.trade_manager.get_coins_of_interest()
        all_coin_names.extend(removed_dict.keys())
        all_coin_names.extend(added_dict.keys())
        await self.subscribe_to_coin_updates(all_coin_names, full_node, request_height)
        self.wallet_state_manager.set_sync_mode(False)
        end_time = time.time()
        duration = end_time - start_time
        self.log.info(f"Duration was: {duration}")
        # Refresh wallets
        for wallet_id, wallet in self.wallet_state_manager.wallets.items():
            self.wallet_state_manager.state_changed("coin_removed", wallet_id)
            self.wallet_state_manager.state_changed("coin_added", wallet_id)
        self.synced_peers.add(full_node.peer_node_id)

    async def subscribe_to_phs(self, puzzle_hashes, full_node=None, height=uint32(0)):
        if full_node is None:
            peer = self.get_full_node_peer()
        else:
            peer = full_node
        if peer is None:
            return
        msg = wallet_protocol.RegisterForPhUpdates(puzzle_hashes, height)
        all_state: Union[Optional, RespondToPhUpdates] = await peer.register_interest_in_puzzle_hash(msg)
        if all_state is not None and full_node is not None:
            await self.handle_coin_state_change(all_state.coin_states)

    async def subscribe_to_coin_updates(self, coin_names, full_node=None, height=uint32(0)):
        if full_node is None:
            peer = self.get_full_node_peer()
        else:
            peer = full_node
        if peer is None:
            return
        msg = wallet_protocol.RegisterForCoinUpdates(coin_names, height)
        all_coins_state: Optional[RespondToCoinUpdates] = await peer.register_interest_in_coin(msg)
        if all_coins_state is not None and full_node is not None:
            await self.handle_coin_state_change(all_coins_state.coin_states)

    async def get_coin_state(self, coin_names) -> List[CoinState]:
        assert self.server is not None
        all_nodes = self.server.connection_by_type[NodeType.FULL_NODE]
        if len(all_nodes.keys()) == 0:
            raise ValueError("Not connected to the full node")
        first_node = list(all_nodes.values())[0]
        msg = wallet_protocol.RegisterForCoinUpdates(coin_names, uint32(0))
        coin_state: Optional[RespondToCoinUpdates] = await first_node.register_interest_in_coin(msg)
        assert coin_state is not None
        return coin_state.coin_states

    async def get_coins_with_puzzle_hash(self, puzzle_hash) -> List[CoinState]:
        assert self.wallet_state_manager is not None
        assert self.server is not None
        all_nodes = self.server.connection_by_type[NodeType.FULL_NODE]
        if len(all_nodes.keys()) == 0:
            raise ValueError("Not connected to the full node")
        first_node = list(all_nodes.values())[0]
        msg = wallet_protocol.RegisterForPhUpdates(puzzle_hash, uint32(0))
        coin_state: Optional[RespondToPhUpdates] = await first_node.register_interest_in_puzzle_hash(msg)
        assert coin_state is not None
        return coin_state.coin_states

    async def state_update_received(self, request: wallet_protocol.CoinStateUpdate, peer):
        assert self.wallet_state_manager is not None
        async with self.wallet_state_manager.lock:
            if self.server.is_trusted_peer(peer, self.config["trusted_peers"]):
                await self.handle_coin_state_change(request.items, request.fork_height, request.height)
            else:
                # Ignore state_update_received if untrusted, we'll sync from block messages where we check filter
                pass

    async def handle_coin_state_change(self, state_updates: List[CoinState], fork_height=None, height=None):
        assert self.wallet_state_manager is not None
        added, removed = await self.wallet_state_manager.new_coin_state(state_updates, fork_height, height)
        if len(removed) > 0:
            for wallet_id, wallet in self.wallet_state_manager.wallets.items():
                self.wallet_state_manager.state_changed("coin_removed", wallet_id)
        if len(added) > 0:
            for wallet_id, wallet in self.wallet_state_manager.wallets.items():
                self.wallet_state_manager.state_changed("coin_added", wallet_id)
        additional_coin_spends = await self.process_removals(removed)
        if len(additional_coin_spends) > 0:
            created_pool_wallet_ids: List[int] = []
            for cs, height in additional_coin_spends:
                if cs.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
                    already_have = False
                    for wallet_id, wallet in self.wallet_state_manager.wallets.items():
                        if (
                            wallet.type() == WalletType.POOLING_WALLET
                            and (await wallet.get_current_state()).launcher_id == cs.coin.name()
                        ):
                            self.log.warning("Already have, not recreating")
                            already_have = True
                    if not already_have:
                        try:
                            pool_state = solution_to_pool_state(cs)
                        except Exception as e:
                            self.log.debug(f"Not a pool wallet launcher {e}")
                            continue
                        if pool_state is None:
                            self.log.debug("Not a pool wallet launcher")
                            continue
                        self.log.info("Found created launcher. Creating pool wallet")
                        pool_wallet = await PoolWallet.create(
                            self.wallet_state_manager,
                            self.wallet_state_manager.main_wallet,
                            cs.coin.name(),
                            additional_coin_spends,
                            True,
                            "pool_wallet",
                        )
                        created_pool_wallet_ids.append(pool_wallet.wallet_id)
                        self.log.info(f"wallet ids: {created_pool_wallet_ids}")

            for wallet_id, wallet in self.wallet_state_manager.wallets.items():
                if wallet.type() == WalletType.POOLING_WALLET:
                    await wallet.apply_state_transitions(additional_coin_spends)

    def get_full_node_peer(self):
        nodes = self.server.get_full_node_connections()
        if len(nodes) > 0:
            return nodes[0]
        else:
            return None

    async def process_removals(self, removed_coins: List[CoinState]):
        assert self.wallet_state_manager is not None

        peer = self.get_full_node_peer()
        assert peer is not None
        additional_coin_spends = []
        for state in removed_coins:
            children: List[CoinState] = await self.fetch_children(peer, state.coin.name())
            for coin_state in children:
                # This searches specifically for a launcher being created, and adds the solution of the launcher
                if coin_state.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH and state.spent_height is not None:
                    cs: CoinSpend = await self.fetch_puzzle_solution(peer, state.spent_height, coin_state.coin)
                    additional_coin_spends.append((cs, state.spent_height))
                    # Apply this coin solution, which might add things to interested list
                    await self.wallet_state_manager.get_next_interesting_coin_ids(cs, False)

            keep_searching = True
            checked = set()
            while keep_searching:
                keep_searching = False
                interested_ids: List[
                    bytes32
                ] = await self.wallet_state_manager.interested_store.get_interested_coin_ids()
                for coin_id in interested_ids:
                    if coin_id in checked:
                        continue
                    coin_states = await self.get_coin_state([coin_id])
                    coin_state = coin_states[0]
                    if coin_state.spent_height == state.spent_height and state.spent_height is not None:
                        cs = await self.fetch_puzzle_solution(peer, state.spent_height, coin_state.coin)
                        await self.wallet_state_manager.get_next_interesting_coin_ids(cs, False)
                        additional_coin_spends.append((cs, state.spent_height))
                        keep_searching = True
                        checked.add(coin_id)
                        break

        return additional_coin_spends

    async def _periodically_check_full_node(self) -> None:
        tries = 0
        while not self._shut_down and tries < 5:
            if self.has_full_node():
                if self.wallet_state_manager is not None:
                    self.wallet_state_manager.state_changed("add_connection")
                break
            tries += 1
            await asyncio.sleep(self.config["peer_connect_interval"])

    def has_full_node(self) -> bool:
        if self.server is None:
            return False
        if "full_node_peer" in self.config:
            full_node_peer = PeerInfo(
                self.config["full_node_peer"]["host"],
                self.config["full_node_peer"]["port"],
            )
            peers = [c.get_peer_info() for c in self.server.get_full_node_connections()]
            full_node_resolved = PeerInfo(socket.gethostbyname(full_node_peer.host), full_node_peer.port)
            if full_node_peer in peers or full_node_resolved in peers:
                self.log.info(f"Will not attempt to connect to other nodes, already connected to {full_node_peer}")
                for connection in self.server.get_full_node_connections():
                    if (
                        connection.get_peer_info() != full_node_peer
                        and connection.get_peer_info() != full_node_resolved
                    ):
                        self.log.info(f"Closing unnecessary connection to {connection.get_peer_info()}.")
                        asyncio.create_task(connection.close())
                return True
        return False

    async def fetch_last_tx_from_peer(self, height, peer) -> Optional[HeaderBlock]:
        request_height = height
        while True:
            if request_height == 0:
                return None
            request = wallet_protocol.RequestBlockHeader(request_height)
            response: Optional[RespondBlockHeader] = await peer.request_block_header(request)
            if response is not None and isinstance(response, RespondBlockHeader):
                if response.header_block.is_transaction_block:
                    return response.header_block
            else:
                break
            request_height -= 1
        return None

    async def fetch_block(self, height):
        peer = self.get_full_node_peer()
        assert peer is not None
        request = wallet_protocol.RequestBlockHeader(height)
        response: Optional[RespondBlockHeader] = await peer.request_block_header(request)
        if response is not None and isinstance(response, RespondBlockHeader):
            return response.header_block

    async def get_timestamp_for_height(self, height):
        if height in self.height_to_time:
            return self.height_to_time[height]

        header_block = await self.fetch_block(height)
        time = header_block.foliage_transaction_block.timestamp
        self.height_to_time[height] = time
        return time

    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection):
        assert self.wallet_state_manager is not None
        current_peak = self.wallet_state_manager.blockchain.peak
        async with self.new_peak_lock:
            if self.server.is_trusted_peer(peer, self.config["trusted_peers"]):
                async with self.wallet_state_manager.lock:
                    if peer.peer_node_id not in self.synced_peers:
                        await self.update_coin_state(peer)
                        await self.wallet_state_manager.blockchain.set_synced_height(peak.height)

                    await self.wallet_state_manager.new_peak(peak)
                    last_tx: Optional[HeaderBlock] = await self.fetch_last_tx_from_peer(peak.height, peer)
                    if last_tx is not None:
                        await self.wallet_state_manager.blockchain.set_latest_tx_block(last_tx)

                    self.wallet_state_manager.state_changed("new_block")
                    self.wallet_state_manager.set_sync_mode(False)
            else:
                request = wallet_protocol.RequestBlockHeader(peak.height)
                response: Optional[RespondBlockHeader] = await peer.request_block_header(request)
                if response is None or not isinstance(response, RespondBlockHeader) or response.header_block is None:
                    self.log.warning(f"bad peak response from peer {response}")
                    return
                peak_block = response.header_block
                if (
                    self.wallet_state_manager.blockchain.peak is not None
                    and peak_block.weight < self.wallet_state_manager.blockchain.peak.weight
                ):
                    return

                curr_peak_height = 0 if current_peak is None else current_peak.height

                # check if claimed peak is heavier or same as our current peak

                # don't sync if full node is not synced it self
                # if not response.header_block.is_transaction_block:
                #     last_tx_block = await self.fetch_last_tx_from_peer(response.header_block.height, peer)
                # else:
                #     last_tx_block = response.header_block
                # assert last_tx_block is not None
                # if last_tx_block.foliage_transaction_block.timestamp < int(time.time()) - 600:
                #     # Full node not synced, don't sync to it
                #     await peer.close()
                #     return

                if (
                    peer.peer_node_id not in self.synced_peers
                    and peak.height >= self.constants.WEIGHT_PROOF_RECENT_BLOCKS
                ):
                    self.wallet_state_manager.set_sync_mode(True)

                    valid_weight_proof, weight_proof = await self.fetch_and_validate_the_weight_proof(
                        peer, response.header_block
                    )
                    if valid_weight_proof is False:
                        await peer.close()
                        return

                    await self.untrusted_sync_to_peer(peer, peak, weight_proof)
                    self.wallet_state_manager.blockchain.new_weight_proof(weight_proof)
                    self.wallet_state_manager.set_sync_mode(False)
                    self.synced_peers.add(peer.peer_node_id)
                else:
                    await self.wallet_short_sync_backtrack(peak_block, peer)

    async def wallet_short_sync_backtrack(self, header_block, peer):
        top = header_block
        blocks = [top]
        # Fetch blocks backwards until we hit the one that we have,
        # then complete them with additions / removals going forward
        fork_height = 0
        if self.wallet_state_manager.blockchain.contains_block(header_block.prev_header_hash):
            fork_height = header_block.height - 1

        while not self.wallet_state_manager.blockchain.contains_block(top.prev_header_hash) and top.height > 0:
            request_prev = wallet_protocol.RequestBlockHeader(top.height - 1)
            response_prev: Optional[RespondBlockHeader] = await peer.request_block_header(request_prev)
            if response_prev is None or not isinstance(response_prev, RespondBlockHeader):
                raise RuntimeError("bad block header response from peer while syncing")
            prev_head = response_prev.header_block
            blocks.append(prev_head)
            top = prev_head
            fork_height = top.height - 1

        max = 60
        current_count = 0
        bottom = blocks[-1]
        while not current_count > max and bottom.height > 0:
            previous = self.wallet_state_manager.blockchain.recent_blocks_dict.get(bottom.prev_header_hash)
            if previous is None:
                break
            current_count += 1
            bottom = previous

        blocks.reverse()
        found_ses_hash = None

        if self.wallet_state_manager.blockchain.peak is not None:
            # Find previous last difficulty and last sub slot iters
            last_dificulty = self.constants.DIFFICULTY_STARTING
            last_sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING

            # Try to find latest SES data by going backwards from peak
            current = self.wallet_state_manager.blockchain.peak
            while True:
                current: Optional[HeaderBlock] = self.wallet_state_manager.blockchain.recent_blocks_dict.get(
                    current.prev_header_hash
                )
                if current is None:
                    break

                if len(current.finished_sub_slots) > 0:
                    for sub_slot in current.finished_sub_slots:
                        if sub_slot.challenge_chain.subepoch_summary_hash is not None:
                            found_ses_hash = sub_slot.challenge_chain.subepoch_summary_hash
                            last_dificulty = current.finished_sub_slots[0].challenge_chain.new_difficulty
                            last_sub_slot_iters = current.finished_sub_slots[0].challenge_chain.new_sub_slot_iters
                            break

            # IF we didn't find SES data above use the last SES from the weight proof
            wp = self.wallet_state_manager.blockchain.synced_weight_proof
            if found_ses_hash is None and wp is not None:
                if top.height > wp.recent_chain_data[0].height:
                    for ses in wp.sub_epochs:
                        if ses.new_difficulty is not None:
                            last_difficulty = ses.new_difficulty
                        if ses.new_sub_slot_iters is not None:
                            last_sub_slot_iters = ses.new_sub_slot_iters
        else:
            last_dificulty = self.constants.DIFFICULTY_STARTING
            last_sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING

        validation_dict = self.wallet_state_manager.blockchain.recent_blocks_dict.copy()
        for block in blocks:
            validation_dict[block.header_hash] = block
        validation = self.validate_weight_in_span(blocks, last_dificulty, last_sub_slot_iters, validation_dict)

        await self.wallet_state_manager.reorg_rollback(fork_height)
        header_block_record = await self.complete_blocks(blocks, peer)
        await self.wallet_state_manager.blockchain.new_recent_blocks(blocks)
        await self.wallet_state_manager.create_more_puzzle_hashes()

    async def complete_blocks(self, header_blocks: List[HeaderBlock], peer: WSChiaConnection):
        if self.wallet_state_manager is None:
            return None
        header_block_records: List[HeaderBlockRecord] = []
        coin_states = []
        all_outgoing_per_wallet: Dict[int, List[TransactionRecord]] = {}
        trade_removals, trade_additions = await self.wallet_state_manager.trade_manager.get_coins_of_interest()

        for block in header_blocks:
            if block.is_transaction_block:
                # Find additions and removals
                (additions, removals,) = await self.wallet_state_manager.get_filter_additions_removals(
                    block, block.transactions_filter, None
                )

                # Get Additions
                added_coins = await self.get_additions(peer, block, additions)
                if added_coins is None:
                    raise ValueError("Failed to fetch additions")

                # Get removals
                removed_coins = await self.get_removals(peer, block, added_coins, removals)
                if removed_coins is None:
                    raise ValueError("Failed to fetch removals")
                # If there is a launcher created, or we have a singleton spent, fetches the required solutions
                additional_coin_spends: List[CoinSpend] = await self.get_additional_coin_spends(
                    peer, block, added_coins, removed_coins
                )

                hbr = HeaderBlockRecord(block, added_coins, removed_coins)
                header_block_records.append(hbr)

                for added_coin in added_coins:
                    wallet_info = await self.wallet_state_manager.get_wallet_id_for_puzzle_hash(added_coin.puzzle_hash)
                    if wallet_info is None:
                        continue
                    wallet_id, wallet_type = wallet_info
                    if wallet_id in all_outgoing_per_wallet:
                        all_outgoing = all_outgoing_per_wallet[wallet_id]
                    else:
                        all_outgoing = await self.wallet_state_manager.tx_store.get_all_transactions_for_wallet(
                            wallet_id, TransactionType.OUTGOING_TX
                        )
                        all_outgoing_per_wallet[wallet_id] = all_outgoing
                    await self.wallet_state_manager.coin_added(
                        added_coin, block.height, all_outgoing, wallet_id, wallet_type, trade_additions
                    )

                for removed_coin in removed_coins:
                    record = await self.wallet_state_manager.coin_store.get_coin_record(removed_coin.name())
                    if record is None:
                        continue
                    await self.wallet_state_manager.coin_store.set_spent(removed_coin.name(), block.height)

        return header_block_records

    async def get_additional_coin_spends(
        self, peer, block, added_coins: List[Coin], removed_coins: List[Coin]
    ) -> List[CoinSpend]:
        assert self.wallet_state_manager is not None
        additional_coin_spends: List[CoinSpend] = []
        if len(removed_coins) > 0:
            removed_coin_ids = set([coin.name() for coin in removed_coins])
            all_added_coins = await self.get_additions(peer, block, [], get_all_additions=True)
            assert all_added_coins is not None
            if all_added_coins is not None:

                for coin in all_added_coins:
                    # This searches specifically for a launcher being created, and adds the solution of the launcher
                    if coin.puzzle_hash == SINGLETON_LAUNCHER_HASH and coin.parent_coin_info in removed_coin_ids:
                        cs: CoinSpend = await self.fetch_puzzle_solution(peer, block.height, coin)
                        additional_coin_spends.append(cs)
                        # Apply this coin solution, which might add things to interested list
                        await self.wallet_state_manager.get_next_interesting_coin_ids(cs, False)

                all_removed_coins: Optional[List[Coin]] = await self.get_removals(
                    peer, block, added_coins, removed_coins, request_all_removals=True
                )
                assert all_removed_coins is not None
                all_removed_coins_dict: Dict[bytes32, Coin] = {coin.name(): coin for coin in all_removed_coins}
                keep_searching = True
                while keep_searching:
                    # This keeps fetching solutions for coins we are interested list, in this block, until
                    # there are no more interested things to fetch
                    keep_searching = False
                    interested_ids: List[
                        bytes32
                    ] = await self.wallet_state_manager.interested_store.get_interested_coin_ids()
                    for coin_id in interested_ids:
                        if coin_id in all_removed_coins_dict:
                            coin = all_removed_coins_dict[coin_id]
                            cs = await self.fetch_puzzle_solution(peer, block.height, coin)

                            # Apply this coin solution, which might add things to interested list
                            await self.wallet_state_manager.get_next_interesting_coin_ids(cs, False)
                            additional_coin_spends.append(cs)
                            keep_searching = True
                            all_removed_coins_dict.pop(coin_id)
                            break
        return additional_coin_spends

    async def get_additions(
        self, peer: WSChiaConnection, block_i, additions: Optional[List[bytes32]], get_all_additions: bool = False
    ) -> Optional[List[Coin]]:
        if (additions is not None and len(additions) > 0) or get_all_additions:
            if get_all_additions:
                additions = None
            additions_request = RequestAdditions(block_i.height, block_i.header_hash, additions)
            additions_res: Optional[Union[RespondAdditions, RejectAdditionsRequest]] = await peer.request_additions(
                additions_request
            )
            if additions_res is None:
                await peer.close()
                return None
            elif isinstance(additions_res, RespondAdditions):
                validated = self.validate_additions(
                    additions_res.coins,
                    additions_res.proofs,
                    block_i.foliage_transaction_block.additions_root,
                )
                if not validated:
                    await peer.close()
                    return None
                added_coins = []
                for ph_coins in additions_res.coins:
                    ph, coins = ph_coins
                    added_coins.extend(coins)
                return added_coins
            elif isinstance(additions_res, RejectRemovalsRequest):
                await peer.close()
                return None
            return None
        else:
            return []  # No added coins

    async def get_removals(
        self, peer: WSChiaConnection, block_i, additions, removals, request_all_removals=False
    ) -> Optional[List[Coin]]:
        assert self.wallet_state_manager is not None
        # Check if we need all removals
        for coin in additions:
            puzzle_store = self.wallet_state_manager.puzzle_store
            record_info: Optional[DerivationRecord] = await puzzle_store.get_derivation_record_for_puzzle_hash(
                coin.puzzle_hash.hex()
            )
            if record_info is not None and record_info.wallet_type == WalletType.COLOURED_COIN:
                # TODO why ?
                request_all_removals = True
                break
            if record_info is not None and record_info.wallet_type == WalletType.DISTRIBUTED_ID:
                request_all_removals = True
                break
        if len(removals) > 0 or request_all_removals:
            if request_all_removals:
                removals_request = wallet_protocol.RequestRemovals(block_i.height, block_i.header_hash, None)
            else:
                removals_request = wallet_protocol.RequestRemovals(block_i.height, block_i.header_hash, removals)
            removals_res: Optional[Union[RespondRemovals, RejectRemovalsRequest]] = await peer.request_removals(
                removals_request
            )
            if removals_res is None:
                return None
            elif isinstance(removals_res, RespondRemovals):
                validated = self.validate_removals(
                    removals_res.coins,
                    removals_res.proofs,
                    block_i.foliage_transaction_block.removals_root,
                )
                if validated is False:
                    await peer.close()
                    return None
                removed_coins = []
                for _, coins_l in removals_res.coins:
                    if coins_l is not None:
                        removed_coins.append(coins_l)

                return removed_coins
            elif isinstance(removals_res, RejectRemovalsRequest):
                return None
            else:
                return None

        else:
            return []

    async def fetch_and_validate_the_weight_proof(self, peer, peak) -> Tuple[bool, Optional[WeightProof]]:
        weight_request = RequestProofOfWeight(peak.height, peak.header_hash)
        weight_proof_response: RespondProofOfWeight = await peer.request_proof_of_weight(weight_request, timeout=360)

        if weight_proof_response is None:
            return False, None
        weight_proof = weight_proof_response.wp
        start_validation = time.time()
        (
            valid,
            fork_point,
            _,
        ) = await self.wallet_state_manager.weight_proof_handler.validate_weight_proof(weight_proof)

        end_validation = time.time()
        self.log.warning(f"It took {end_validation - start_validation} time to validate the weight proof!!!")
        return valid, weight_proof

    async def untrusted_sync_to_peer(self, peer, peak: wallet_protocol.NewPeakWallet, weight_proof):
        start_time = time.time()
        peer_request_cache = PeerRequestCache()
        all_puzzle_hashes = list(await self.wallet_state_manager.puzzle_store.get_all_puzzle_hashes())
        current_height = await self.wallet_state_manager.blockchain.get_synced_height()
        # Get state for puzzle hashes
        msg = wallet_protocol.RegisterForPhUpdates(all_puzzle_hashes, uint32(0))
        all_state: Optional[RespondToPhUpdates] = await peer.register_interest_in_puzzle_hash(msg)

        await self.validate_received_state_from_peer(all_state.coin_states, peer, weight_proof, peer_request_cache)
        # Apply validated state
        await self.handle_coin_state_change(all_state.coin_states)

        # Get state for coins ids
        all_coins = await self.wallet_state_manager.coin_store.get_coins_to_check(uint32(0))
        all_coin_names = [coin_record.name() for coin_record in all_coins]
        removed_dict, added_dict = await self.wallet_state_manager.trade_manager.get_coins_of_interest()
        all_coin_names.extend(removed_dict.keys())
        all_coin_names.extend(added_dict.keys())
        msg = wallet_protocol.RegisterForCoinUpdates(all_coin_names, uint32(0))
        all_coins_state: Optional[RespondToCoinUpdates] = await peer.register_interest_in_coin(msg)
        await self.validate_received_state_from_peer(all_state.coin_states, peer, weight_proof, peer_request_cache)
        # Apply validated state
        await self.handle_coin_state_change(all_state.coin_states)
        end_time = time.time()
        duration = end_time - start_time
        self.log.info(f"Sync duration was: {duration}")

    async def validate_received_state_from_peer(
        self, coin_states: List[CoinState], peer, weight_proof: WeightProof, peer_request_cache: PeerRequestCache
    ):
        total = len(coin_states)

        for coin_idx, coin_state in enumerate(coin_states):
            self.log.info(f"Validating {coin_idx} of {total}")
            if coin_state.get_hash() in peer_request_cache.states_validated:
                continue

            spent_height = coin_state.spent_height
            confirmed_height = coin_state.created_height
            current = await self.wallet_state_manager.coin_store.get_coin_record(coin_state.coin.name())
            # if remote state is same as current local state we skip validation
            # if (
            #     current is not None
            #     and current.spent_block_height == spent_height
            #     and current.confirmed_block_height == confirmed_height
            # ):

            if current == 1:
                if current.spent_block_height != spent_height:
                    pass
                elif current.confirmed_block_height != confirmed_height:
                    pass
            else:
                # Full info validation
                if confirmed_height is None:
                    # We shouldn't receive state for non-existing coin unless we specifically ask for it
                    peer.close(9999)
                    return

                # request header block for created height
                if confirmed_height in peer_request_cache.blocks:
                    state_block: FullBlock = peer_request_cache.blocks[confirmed_height]
                else:
                    request = RequestBlocks(confirmed_height, confirmed_height, True)
                    res = await peer.request_blocks(request)
                    state_block = res.blocks[0]
                    peer_request_cache.blocks[confirmed_height] = state_block

                # get proof of inclusion
                validate_additions = await self.request_and_validate_additions(
                    peer,
                    state_block.height,
                    state_block.header_hash,
                    coin_state.coin.puzzle_hash,
                    state_block.foliage_transaction_block.additions_root,
                )

                if validate_additions is False:
                    peer.close(9999)
                    return

                # get blocks on top of this block

                validated = await self.validate_state(weight_proof, state_block, peer, peer_request_cache)
                if not validated:
                    raise ValueError("Validation failed")

                if spent_height is not None:
                    # request header block for created height
                    if spent_height in peer_request_cache.blocks:
                        spent_state_block: FullBlock = peer_request_cache.blocks[spent_height]
                    else:
                        request = RequestBlocks(spent_height, spent_height, True)
                        res = await peer.request_blocks(request)
                        spent_state_block = res.blocks[0]
                        peer_request_cache.blocks[spent_height] = spent_state_block

                    validate_removals = await self.request_and_validate_removals(
                        peer,
                        spent_state_block.height,
                        spent_state_block.header_hash,
                        coin_state.coin.name(),
                        spent_state_block.foliage_transaction_block.removals_root,
                    )
                    if validate_removals is False:
                        peer.close(9999)
                        return
                    validated = await self.validate_state(weight_proof, spent_state_block, peer, peer_request_cache)
                    if not validated:
                        raise ValueError("Validation failed")
            peer_request_cache.states_validated[coin_state.get_hash()] = coin_state

    async def request_and_validate_removals(self, peer, height, header_hash, coin_name, removals_root):
        removals_request = wallet_protocol.RequestRemovals(height, header_hash, [coin_name])

        removals_res: Optional[Union[RespondRemovals, RejectRemovalsRequest]] = await peer.request_removals(
            removals_request
        )
        if removals_res is None or isinstance(removals_res, RejectRemovalsRequest):
            return False
        return self.validate_removals(removals_res.coins, removals_res.proofs, removals_root)

    def validate_removals(self, coins, proofs, root):
        if proofs is None:
            # If there are no proofs, it means all removals were returned in the response.
            # we must find the ones relevant to our wallets.

            # Verify removals root
            removals_merkle_set = MerkleSet()
            for name_coin in coins:
                name, coin = name_coin
                if coin is not None:
                    removals_merkle_set.add_already_hashed(coin.name())
            removals_root = removals_merkle_set.get_root()
            if root != removals_root:
                return False
        else:
            # This means the full node has responded only with the relevant removals
            # for our wallet. Each merkle proof must be verified.
            if len(coins) != len(proofs):
                return False
            for i in range(len(coins)):
                # Coins are in the same order as proofs
                if coins[i][0] != proofs[i][0]:
                    return False
                coin = coins[i][1]
                if coin is None:
                    # Verifies merkle proof of exclusion
                    not_included = confirm_not_included_already_hashed(
                        root,
                        coins[i][0],
                        proofs[i][1],
                    )
                    if not_included is False:
                        return False
                else:
                    # Verifies merkle proof of inclusion of coin name
                    if coins[i][0] != coin.name():
                        return False
                    included = confirm_included_already_hashed(
                        root,
                        coin.name(),
                        proofs[i][1],
                    )
                    if included is False:
                        return False
        return True

    async def request_and_validate_additions(self, peer, height, header_hash, puzzle_hash, additions_root):
        additions_request = RequestAdditions(height, header_hash, [puzzle_hash])
        additions_res: Optional[Union[RespondAdditions, RejectAdditionsRequest]] = await peer.request_additions(
            additions_request
        )
        if additions_res is None or isinstance(additions_res, RejectAdditionsRequest):
            return False

        validated = self.validate_additions(
            additions_res.coins,
            additions_res.proofs,
            additions_root,
        )
        return validated

    async def validate_state(
        self, weight_proof: WeightProof, block: FullBlock, peer, peer_request_cache: PeerRequestCache
    ) -> bool:

        wp_peak = weight_proof.recent_chain_data[-1].height
        first_wp_block = weight_proof.recent_chain_data[0].height

        if block.height >= weight_proof.recent_chain_data[0].height:
            # this was already validated as part of the wp validation
            index = block.height - weight_proof.recent_chain_data[0].height
            assert weight_proof.recent_chain_data[index].header_hash == block.header_hash
        else:
            request = RequestSESInfo(block.height, block.height + 32)
            if request.get_hash() in peer_request_cache.ses_requests:
                res_ses = peer_request_cache.ses_requests[request.get_hash()]
            else:
                res_ses: RespondSESInfo = await peer.request_ses_hashes(request)

            ses_0 = res_ses.reward_chain_hash[0]
            last_height = res_ses.heights[0][-1]
            blocks = []
            blocks_dict = {}
            diff = last_height - block.height
            start = block.height
            end = last_height
            # get at least 50 block to check
            if diff < 50:
                start -= 50 - diff
            elif diff > 96:
                end = start + 96

            for i in range(start, end + 1, 32):
                request_h_response = RequestBlocks(min(i, last_height), min(i + 31, last_height), True)
                if request_h_response.get_hash() in peer_request_cache.block_requests:
                    res_h_blocks: RespondBlocks = peer_request_cache.block_requests[request_h_response.get_hash()]
                else:
                    res_h_blocks: RespondBlocks = await peer.request_blocks(request_h_response)
                    peer_request_cache.block_requests[request_h_response.get_hash()] = res_h_blocks
                self.log.error(
                    f"First height: {res_h_blocks.blocks[0].height}, Last height: {res_h_blocks.blocks[-1].height} "
                )
                blocks.extend(res_h_blocks.blocks)
                for block in res_h_blocks.blocks:
                    blocks_dict[block.header_hash] = block

            # last_reward = blocks[-1].finished_sub_slots[-1].reward_chain.get_hash()

            in_chain = False
            ses_index = None
            current_ses: Optional[SubEpochData] = None
            last_difficulty = self.constants.DIFFICULTY_STARTING
            last_sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING
            for idx, ses in enumerate(weight_proof.sub_epochs):
                if ses.new_difficulty is not None:
                    last_difficulty = ses.new_difficulty
                if ses.new_sub_slot_iters is not None:
                    last_sub_slot_iters = ses.new_sub_slot_iters
                if ses.reward_chain_hash == ses_0:
                    current_ses = ses
                    ses_index = idx
                    break

            assert current_ses is not None

            last_tx_block = None
            reversed_blocks = blocks.copy()
            reversed_blocks.reverse()

            challenge_none = 0
            slots_count = 0

            weight_validated = self.validate_weight_in_span(blocks, last_difficulty, last_sub_slot_iters, blocks_dict)

            return weight_validated

    def validate_weight_in_span(self, blocks, last_difficulty, last_sub_slot_iters, blocks_dict):
        reversed_blocks = blocks.copy()
        reversed_blocks.reverse()
        last_tx_block = None
        challenge_none = 0
        slots_count = 0

        for idx, block in enumerate(reversed_blocks):

            if idx != 0:
                if block.header_hash != reversed_blocks[idx - 1].prev_header_hash:
                    pass

            if block.is_transaction_block and last_tx_block is None:
                last_tx_block = block
            elif block.is_transaction_block and last_tx_block is not None:
                if last_tx_block.foliage_transaction_block.prev_transaction_block_hash != block.header_hash:
                    return False
                else:
                    last_tx_block = block

            if block.foliage.foliage_transaction_block_hash is not None:
                valid = AugSchemeMPL.verify(
                    block.reward_chain_block.proof_of_space.plot_public_key,
                    block.foliage.foliage_transaction_block_hash,
                    block.foliage.foliage_transaction_block_signature,
                )
                if not valid:
                    return False

            overflow = is_overflow_block(self.constants, block.reward_chain_block.signage_point_index)
            challenge = self.get_block_challenge(self.constants, block, blocks_dict, False, overflow, False)

            if challenge is not None:
                if block.reward_chain_block.challenge_chain_sp_vdf is None:
                    # Edge case of first sp (start of slot), where sp_iters == 0
                    cc_sp_hash: bytes32 = challenge
                else:
                    cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()

                q_str: Optional[bytes32] = block.reward_chain_block.proof_of_space.verify_and_get_quality_string(
                    self.constants, challenge, cc_sp_hash
                )

                if q_str is None:
                    return False

                required_iters: uint64 = calculate_iterations_quality(
                    self.constants.DIFFICULTY_CONSTANT_FACTOR,
                    q_str,
                    block.reward_chain_block.proof_of_space.size,
                    last_difficulty,
                    cc_sp_hash,
                )

                if required_iters >= calculate_sp_interval_iters(self.constants, last_sub_slot_iters):
                    return False
            else:
                challenge_none += 1

        total = len(reversed_blocks)
        not_none = total - challenge_none

        return True

    def validate_additions(
        self,
        coins: List[Tuple[bytes32, List[Coin]]],
        proofs: Optional[List[Tuple[bytes32, bytes, Optional[bytes]]]],
        root,
    ):
        if proofs is None:
            # Verify root
            additions_merkle_set = MerkleSet()

            # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
            for puzzle_hash, coins_l in coins:
                additions_merkle_set.add_already_hashed(puzzle_hash)
                additions_merkle_set.add_already_hashed(hash_coin_list(coins_l))

            additions_root = additions_merkle_set.get_root()
            if root != additions_root:
                return False
        else:
            for i in range(len(coins)):
                assert coins[i][0] == proofs[i][0]
                coin_list_1: List[Coin] = coins[i][1]
                puzzle_hash_proof: bytes32 = proofs[i][1]
                coin_list_proof: Optional[bytes32] = proofs[i][2]
                if len(coin_list_1) == 0:
                    # Verify exclusion proof for puzzle hash
                    not_included = confirm_not_included_already_hashed(
                        root,
                        coins[i][0],
                        puzzle_hash_proof,
                    )
                    if not_included is False:
                        return False
                else:
                    try:
                        # Verify inclusion proof for coin list
                        included = confirm_included_already_hashed(
                            root,
                            hash_coin_list(coin_list_1),
                            coin_list_proof,
                        )
                        if included is False:
                            return False
                    except AssertionError:
                        return False
                    try:
                        # Verify inclusion proof for puzzle hash
                        included = confirm_included_already_hashed(
                            root,
                            coins[i][0],
                            puzzle_hash_proof,
                        )
                        if included is False:
                            return False
                    except AssertionError:
                        return False

        return True

    def get_block_challenge(
        self,
        constants: ConsensusConstants,
        header_block: FullBlock,
        all_blocks: Dict[bytes32, FullBlock],
        genesis_block: bool,
        overflow: bool,
        skip_overflow_last_ss_validation: bool,
    ) -> Optional[bytes32]:
        if len(header_block.finished_sub_slots) > 0:
            if overflow:
                # New sub-slot with overflow block
                if skip_overflow_last_ss_validation:
                    # In this case, we are missing the final sub-slot bundle (it's not finished yet), however
                    # There is a whole empty slot before this block is infused
                    challenge: bytes32 = header_block.finished_sub_slots[-1].challenge_chain.get_hash()
                else:
                    challenge = header_block.finished_sub_slots[
                        -1
                    ].challenge_chain.challenge_chain_end_of_slot_vdf.challenge
            else:
                # No overflow, new slot with a new challenge
                challenge = header_block.finished_sub_slots[-1].challenge_chain.get_hash()
        else:
            if genesis_block:
                challenge = constants.GENESIS_CHALLENGE
            else:
                if overflow:
                    if skip_overflow_last_ss_validation:
                        # Overflow infusion without the new slot, so get the last challenge
                        challenges_to_look_for = 1
                    else:
                        # Overflow infusion, so get the second to last challenge. skip_overflow_last_ss_validation is False,
                        # Which means no sub slots are omitted
                        challenges_to_look_for = 2
                else:
                    challenges_to_look_for = 1
                reversed_challenge_hashes: List[bytes32] = []
                if header_block.prev_header_hash not in all_blocks:
                    return None
                curr: FullBlock = all_blocks[header_block.prev_header_hash]
                while len(reversed_challenge_hashes) < challenges_to_look_for:
                    if curr is None:
                        return None
                    if len(curr.finished_sub_slots) > 0:
                        reversed_challenge_hashes += reversed(
                            [slot.challenge_chain.get_hash() for slot in curr.finished_sub_slots]
                        )
                    if curr.height == 0:
                        return constants.GENESIS_CHALLENGE

                    curr = all_blocks.get(curr.prev_header_hash, None)
                challenge = reversed_challenge_hashes[challenges_to_look_for - 1]
        return challenge

    async def fetch_puzzle_solution(self, peer, height: uint32, coin: Coin) -> CoinSpend:
        solution_response = await peer.request_puzzle_solution(
            wallet_protocol.RequestPuzzleSolution(coin.name(), height)
        )
        if solution_response is None or not isinstance(solution_response, wallet_protocol.RespondPuzzleSolution):
            raise ValueError(f"Was not able to obtain solution {solution_response}")
        return CoinSpend(coin, solution_response.response.puzzle, solution_response.response.solution)

    async def fetch_children(self, peer, coin_name) -> List[CoinState]:
        response = await peer.request_children(wallet_protocol.RequestChildren(coin_name))
        if response is None or not isinstance(response, wallet_protocol.RespondChildren):
            raise ValueError(f"Was not able to obtain children {response}")
        return response.coin_states
