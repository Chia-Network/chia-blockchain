import asyncio
import json
import logging
import socket
import time
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Union

from blspy import PrivateKey

from chia.consensus.constants import ConsensusConstants
from chia.daemon.keychain_proxy import (
    KeychainProxyConnectionFailure,
    connect_to_keychain_and_validate,
    wrap_local_keychain,
    KeychainProxy,
    KeyringIsEmpty,
)
from chia.pools.pool_puzzles import SINGLETON_LAUNCHER_HASH, solution_to_pool_state
from chia.pools.pool_wallet import PoolWallet
from chia.protocols import wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import (
    RespondToCoinUpdates,
    CoinState,
    RespondToPhUpdates,
    RespondBlockHeader,
)
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32, uint64
from chia.util.keychain import KeyringIsLocked
from chia.util.path import mkdir, path_from_root

from chia.wallet.settings.settings_objects import BackupInitialized
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.backup_utils import open_backup_file
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_action import WalletAction
from chia.util.profiler import profile_task


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
        assert self.server is not None
        trusted = self.server.is_trusted_peer(peer, self.config["trusted_peers"])
        if trusted is False and self.config["testing"] is False:
            await peer.close()
            self.log.error(
                "Wallet connected to the untrusted node. Check your config.yaml for the list of trusted nodes."
            )
            return

        if self.wallet_state_manager is None or self.backup_initialized is False:
            return None
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

    async def state_update_received(self, request: wallet_protocol.CoinStateUpdate):
        assert self.wallet_state_manager is not None
        async with self.wallet_state_manager.lock:
            await self.handle_coin_state_change(request.items, request.fork_height, request.height)

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

    async def fetch_last_tx_block(self, height, peer):
        request_height = height
        current_tx_peak = await self.wallet_state_manager.blockchain.get_latest_tx_block()
        while True:
            if request_height == 0:
                break
            request = wallet_protocol.RequestBlockHeader(request_height)
            response: Optional[RespondBlockHeader] = await peer.request_block_header(request)
            if response is not None and isinstance(response, RespondBlockHeader):
                if request_height == height:
                    await self.wallet_state_manager.blockchain.set_peak_block(response.header_block)
                if response.header_block.is_transaction_block:
                    await self.wallet_state_manager.blockchain.set_latest_tx_block(response.header_block)
                    break
                if (
                    current_tx_peak is not None
                    and response.header_block.prev_header_hash == current_tx_peak.header_hash
                ):
                    # tx peak has not changed
                    break
            else:
                break
            request_height -= 1

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
        async with self.wallet_state_manager.lock:
            if peer.peer_node_id not in self.synced_peers:
                await self.update_coin_state(peer)
                await self.wallet_state_manager.blockchain.set_synced_height(peak.height)

            await self.wallet_state_manager.new_peak(peak)
            await self.fetch_last_tx_block(peak.height, peer)
            self.wallet_state_manager.state_changed("new_block")
            self.wallet_state_manager.set_sync_mode(False)

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
