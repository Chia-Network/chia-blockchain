import asyncio
import json
import logging
import time
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Union, Any

from blspy import PrivateKey, AugSchemeMPL
from packaging.version import Version

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain import ReceiveBlockResult
from chia.consensus.constants import ConsensusConstants
from chia.consensus.find_fork_point import find_fork_point_in_chain
from chia.daemon.keychain_proxy import (
    KeychainProxyConnectionFailure,
    connect_to_keychain_and_validate,
    wrap_local_keychain,
    KeychainProxy,
    KeyringIsEmpty,
)
from chia.full_node.weight_proof import chunks
from chia.pools.pool_puzzles import SINGLETON_LAUNCHER_HASH, solution_to_pool_state
from chia.pools.pool_wallet import PoolWallet
from chia.protocols import wallet_protocol
from chia.protocols.full_node_protocol import RequestProofOfWeight, RespondProofOfWeight
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
    RequestHeaderBlocks,
    RespondHeaderBlocks,
)
from chia.server.node_discovery import WalletPeers
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.peer_store_resolver import PeerStoreResolver
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.coin_spend import CoinSpend
from chia.types.header_block import HeaderBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.types.weight_proof import WeightProof, SubEpochData
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import WALLET_PEERS_PATH_KEY_DEPRECATED
from chia.util.ints import uint32, uint64
from chia.util.keychain import KeyringIsLocked, Keychain
from chia.util.network import get_host_addr
from chia.util.path import mkdir, path_from_root
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.util.wallet_sync_utils import (
    validate_additions,
    validate_removals,
    request_and_validate_removals,
    request_and_validate_additions,
)
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_action import WalletAction
from chia.util.profiler import profile_task


class PeerRequestCache:
    blocks: Dict[uint32, HeaderBlock]
    block_requests: Dict[bytes32, Any]
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
    wallet_peers: Optional[WalletPeers]

    def __init__(
        self,
        config: Dict,
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = None,
        local_keychain: Optional[Keychain] = None,
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
        self.wallet_peers = None
        self.wallet_peers_initialized = False
        self.valid_wp_cache: Dict[bytes32, Any] = {}
        self.untrusted_caches: Dict[bytes32, Any] = {}

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
    ) -> bool:
        self.synced_peers = set()
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

        assert self.wallet_state_manager is not None

        self.config["starting_height"] = 0

        if self.wallet_peers is None:
            self.initialize_wallet_peers()

        if self.state_changed_callback is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)

        self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)
        self._shut_down = False

        self.peer_task = asyncio.create_task(self._periodically_check_full_node())
        self.sync_event = asyncio.Event()
        if fingerprint is None:
            self.logged_in_fingerprint = private_key.get_g1().get_fingerprint()
        else:
            self.logged_in_fingerprint = fingerprint
        self.logged_in = True
        self.wallet_state_manager.set_sync_mode(False)

        async with self.wallet_state_manager.puzzle_store.lock:
            index = await self.wallet_state_manager.puzzle_store.get_last_derivation_path()
            if index is None or index < self.config["initial_num_public_keys"] - 1:
                await self.wallet_state_manager.create_more_puzzle_hashes(from_zero=True)
                self.wsm_close_task = None
        return True

    async def new_puzzle_hash_created(self, puzzle_hashes: List[bytes32]):
        if len(puzzle_hashes) == 0:
            return
        assert self.server is not None
        full_nodes: Dict[bytes32, WSChiaConnection] = self.server.connection_by_type.get(NodeType.FULL_NODE, {})
        for node_id, node in full_nodes.copy().items():
            await self.subscribe_to_phs(puzzle_hashes, node)

    def _close(self):
        self.log.info("self._close")
        self.logged_in_fingerprint = None
        self._shut_down = True

    async def _await_closed(self):
        self.log.info("self._await_closed")
        if self.server is not None:
            await self.server.close_all_connections()
        if self.wallet_peers is not None:
            await self.wallet_peers.ensure_is_closed()
        if self.wallet_state_manager is not None:
            await self.wallet_state_manager._await_closed()
            self.wallet_state_manager = None
        self.logged_in = False
        self.wallet_peers = None

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

        if self.wallet_state_manager is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)
            self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)

    def _pending_tx_handler(self):
        if self.wallet_state_manager is None:
            return None
        asyncio.create_task(self._resend_queue())

    async def _action_messages(self) -> List[Message]:
        if self.wallet_state_manager is None:
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
        if self._shut_down or self.server is None or self.wallet_state_manager is None:
            return None

        for msg, sent_peers in await self._messages_to_resend():
            if self._shut_down or self.server is None or self.wallet_state_manager is None:
                return None
            full_nodes = self.server.get_full_node_connections()
            for peer in full_nodes:
                if peer.peer_node_id in sent_peers:
                    continue
                await peer.send_message(msg)

        for msg in await self._action_messages():
            if self._shut_down or self.server is None or self.wallet_state_manager is None:
                return None
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

    async def _messages_to_resend(self) -> List[Tuple[Message, Set[bytes32]]]:
        if self.wallet_state_manager is None or self._shut_down:
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
                    already_sent.add(bytes32.from_hexstr(peer))
            messages.append((msg, already_sent))

        return messages

    def set_server(self, server: ChiaServer):
        self.server = server
        self.initialize_wallet_peers()

    def initialize_wallet_peers(self):
        self.server.on_connect = self.on_connect
        network_name = self.config["selected_network"]

        connect_to_unknown_peers = self.config.get("connect_to_unknown_peers", False)
        if connect_to_unknown_peers:
            self.wallet_peers = WalletPeers(
                self.server,
                self.config["target_peer_count"],
                PeerStoreResolver(
                    self.root_path,
                    self.config,
                    selected_network=network_name,
                    peers_file_path_key="wallet_peers_file_path",
                    legacy_peer_db_path_key=WALLET_PEERS_PATH_KEY_DEPRECATED,
                    default_peers_file_path="wallet/db/wallet_peers.dat",
                ),
                self.config["introducer_peer"],
                self.config["dns_servers"],
                self.config["peer_connect_interval"],
                network_name,
                None,
                self.log,
            )
            asyncio.create_task(self.wallet_peers.start())

    def on_disconnect(self, peer: WSChiaConnection):
        if peer.peer_node_id in self.untrusted_caches:
            self.untrusted_caches.pop(peer.peer_node_id)

    async def on_connect(self, peer: WSChiaConnection):
        if self.wallet_state_manager is None:
            return None

        if Version(peer.protocol_version) < Version("0.0.33"):
            self.log.info("Disconnecting, full node running old software")
            await peer.close()

        trusted = self.is_trusted(peer)
        self.log.info(f"Connected peer {peer} is {trusted}")
        messages_peer_ids = await self._messages_to_resend()
        self.wallet_state_manager.state_changed("add_connection")
        for msg, peer_ids in messages_peer_ids:
            if peer.peer_node_id in peer_ids:
                continue
            await peer.send_message(msg)

        if not self.has_full_node() and self.wallet_peers is not None:
            asyncio.create_task(self.wallet_peers.on_connect(peer))

    async def trusted_sync(self, full_node: WSChiaConnection):
        """
        Performs a one-time sync with each trusted peer, subscribing to interested puzzle hashes and coin ids.
        """
        self.log.info("Starting trusted sync")
        assert self.wallet_state_manager is not None
        self.wallet_state_manager.set_sync_mode(True)
        start_time = time.time()
        current_height: uint32 = self.wallet_state_manager.blockchain.get_peak_height()
        request_height: uint32 = uint32(max(0, current_height - 1000))

        already_checked: Set[bytes32] = set()
        continue_while: bool = True
        while continue_while:
            # Get all phs from puzzle store
            all_puzzle_hashes: List[bytes32] = await self.get_puzzle_hashes_to_subscribe()
            to_check: List[bytes32] = []
            for ph in all_puzzle_hashes:
                if ph in already_checked:
                    continue
                else:
                    to_check.append(ph)
                    already_checked.add(ph)
                    if len(to_check) == 1000:
                        break

            await self.subscribe_to_phs(to_check, full_node, request_height)

            # Check if new puzzle hashed have been created
            check_again = await self.get_puzzle_hashes_to_subscribe()
            await self.wallet_state_manager.create_more_puzzle_hashes()

            continue_while = False
            for ph in check_again:
                if ph not in already_checked:
                    continue_while = True
                    break

        all_coins: Set[WalletCoinRecord] = await self.wallet_state_manager.coin_store.get_coins_to_check(request_height)
        all_coin_names: List[bytes32] = [coin_record.name() for coin_record in all_coins]
        removed_dict = await self.wallet_state_manager.trade_manager.get_coins_of_interest()
        all_coin_names.extend(removed_dict.keys())

        one_k_chunks = chunks(all_coin_names, 1000)
        for chunk in one_k_chunks:
            await self.subscribe_to_coin_updates(chunk, full_node, request_height)
        self.wallet_state_manager.set_sync_mode(False)
        end_time = time.time()
        duration = end_time - start_time
        self.log.info(f"Trusted sync duration was: {duration}")
        # Refresh wallets
        for wallet_id, wallet in self.wallet_state_manager.wallets.items():
            self.wallet_state_manager.state_changed("coin_removed", wallet_id)
            self.wallet_state_manager.state_changed("coin_added", wallet_id)
        self.synced_peers.add(full_node.peer_node_id)

    async def subscribe_to_phs(self, puzzle_hashes: List[bytes32], peer: WSChiaConnection, height=uint32(0)):
        """
        Tell full nodes that we are interested in puzzle hashes, and for trusted connections, add the new coin state
        for the puzzle hashes.
        """

        msg = wallet_protocol.RegisterForPhUpdates(puzzle_hashes, height)
        all_state: Optional[RespondToPhUpdates] = await peer.register_interest_in_puzzle_hash(msg)
        # State for untrusted sync is processed only in wp sync | or short  sync backwards
        if all_state is not None and self.is_trusted(peer):
            assert self.wallet_state_manager is not None
            await self.wallet_state_manager.new_coin_state(all_state.coin_states, peer)

    async def subscribe_to_coin_updates(self, coin_names, peer, height=uint32(0)):
        """
        Tell full nodes that we are interested in coin ids, and for trusted connections, add the new coin state
        for the coin changes.
        """
        msg = wallet_protocol.RegisterForCoinUpdates(coin_names, height)
        all_coins_state: Optional[RespondToCoinUpdates] = await peer.register_interest_in_coin(msg)
        # State for untrusted sync is processed only in wp sync | or short  sync backwards
        if all_coins_state is not None and self.is_trusted(peer):
            await self.wallet_state_manager.new_coin_state(all_coins_state.coin_states, peer)

    async def get_coin_state(self, coin_names: List[bytes32]) -> List[CoinState]:
        assert self.server is not None
        # TODO Use trusted peer, otherwise try untrusted
        all_nodes = self.server.connection_by_type[NodeType.FULL_NODE]
        if len(all_nodes.keys()) == 0:
            raise ValueError("Not connected to the full node")
        first_node = list(all_nodes.values())[0]
        msg = wallet_protocol.RegisterForCoinUpdates(coin_names, uint32(0))
        coin_state: Optional[RespondToCoinUpdates] = await first_node.register_interest_in_coin(msg)
        # TODO validate state if received from untrusted peer
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

    def is_trusted(self, peer):
        return self.server.is_trusted_peer(peer, self.config["trusted_peers"])

    async def state_update_received(self, request: wallet_protocol.CoinStateUpdate, peer: WSChiaConnection):
        assert self.wallet_state_manager is not None
        assert self.server is not None
        async with self.new_peak_lock:
            async with self.wallet_state_manager.lock:
                if self.is_trusted(peer):
                    await self.wallet_state_manager.new_coin_state(
                        request.items, peer, request.fork_height, request.height
                    )
                    await self.update_ui()
                else:
                    # Ignore state_update_received if untrusted, we'll sync from block messages where we check filter
                    for coin_state in request.items:
                        info = await self.wallet_state_manager.puzzle_store.wallet_info_for_puzzle_hash(
                            coin_state.coin.puzzle_hash
                        )
                        if coin_state.created_height is None or info is not None:
                            continue

                        # We need to check the hints and see if there is a new CAT sent to us, so we can create
                        # a new CAT wallet
                        wallet_id, wallet_type = await self.wallet_state_manager.fetch_parent_and_check_for_cat(
                            peer, coin_state
                        )

                        if wallet_id is not None:
                            # If there is a new wallet, check if we have this height already in the blockchain
                            if self.wallet_state_manager.blockchain.contains_height(request.height):
                                # If we do, complete the blocks
                                header_blocks: Optional[RespondHeaderBlocks] = await peer.request_header_blocks(
                                    wallet_protocol.RequestHeaderBlocks(
                                        request.height, self.wallet_state_manager.blockchain.get_peak_height()
                                    )
                                )
                                assert header_blocks is not None and isinstance(
                                    header_blocks, wallet_protocol.RespondHeaderBlocks
                                )
                                # re-check the block filter for any new addition /removals, for all of the blocks
                                # that have been added to the blockchain since this CAT was created
                                await self.complete_blocks(header_blocks.header_blocks, peer)

    def get_full_node_peer(self):
        nodes = self.server.get_full_node_connections()
        if len(nodes) > 0:
            return nodes[0]
        else:
            return None

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
            # If full_node_peer is already an address, use it, otherwise
            # resolve it here.
            if full_node_peer.is_valid():
                full_node_resolved = full_node_peer
            else:
                full_node_resolved = PeerInfo(
                    get_host_addr(full_node_peer.host, self.config.get("prefer_ipv6")), full_node_peer.port
                )
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

    async def fetch_last_tx_from_peer(self, height: uint32, peer: WSChiaConnection) -> Optional[HeaderBlock]:
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
            request_height = uint32(request_height - 1)
        return None

    async def get_timestamp_for_height(self, height: uint32) -> uint64:
        """
        Returns the timestamp for transaction block at h=height, if not transaction block, backtracks until it finds
        a transaction block
        """
        if height in self.height_to_time:
            return self.height_to_time[height]

        peer = self.get_full_node_peer()
        assert peer is not None
        curr_height: uint32 = height
        while True:
            request = wallet_protocol.RequestBlockHeader(curr_height)
            response: Optional[RespondBlockHeader] = await peer.request_block_header(request)
            if response is None or not isinstance(response, RespondBlockHeader):
                raise ValueError(f"Invalid response from {peer}, {response}")
            if response.header_block.foliage_transaction_block is not None:
                self.height_to_time[height] = response.header_block.foliage_transaction_block.timestamp
                return response.header_block.foliage_transaction_block.timestamp
            curr_height = uint32(curr_height - 1)

    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection):
        assert self.wallet_state_manager is not None
        assert self.server is not None
        async with self.new_peak_lock:
            if self.wallet_state_manager is None:
                # When logging out of wallet
                return
            if self.is_trusted(peer):
                async with self.wallet_state_manager.lock:
                    request = wallet_protocol.RequestBlockHeader(peak.height)
                    header_response: Optional[RespondBlockHeader] = await peer.request_block_header(request)
                    assert header_response is not None

                    last_tx: Optional[HeaderBlock] = await self.fetch_last_tx_from_peer(peak.height, peer)
                    latest_timestamp: Optional[uint64] = None
                    if last_tx is not None:
                        assert last_tx.foliage_transaction_block is not None
                        latest_timestamp = last_tx.foliage_transaction_block.timestamp

                    if peer.peer_node_id not in self.synced_peers:
                        await self.trusted_sync(peer)

                    await self.wallet_state_manager.blockchain.set_peak_block(
                        header_response.header_block, latest_timestamp
                    )

                    self.wallet_state_manager.state_changed("new_block")
                    self.wallet_state_manager.set_sync_mode(False)
            else:
                request = wallet_protocol.RequestBlockHeader(peak.height)
                response: Optional[RespondBlockHeader] = await peer.request_block_header(request)
                if response is None or not isinstance(response, RespondBlockHeader) or response.header_block is None:
                    self.log.debug(f"bad peak response from peer {response}, perhaps connection was closed")
                    return
                peak_block = response.header_block
                current_peak: Optional[HeaderBlock] = await self.wallet_state_manager.blockchain.get_peak_block()
                if current_peak is not None and peak_block.weight < current_peak.weight:
                    if peak_block.height < current_peak.height - 20:
                        await peer.close(120)
                    return

                # don't sync if full node is not synced it self, since we want to fully sync to a few peers
                if (
                    not response.header_block.is_transaction_block
                    and current_peak is not None
                    and peak_block.prev_header_hash == current_peak.header_hash
                ):
                    # This block is after our peak, so we don't need to check if node is synced
                    pass
                else:
                    if not response.header_block.is_transaction_block:
                        last_tx_block = await self.fetch_last_tx_from_peer(response.header_block.height, peer)
                    else:
                        last_tx_block = response.header_block

                    if last_tx_block is None:
                        return
                    assert last_tx_block is not None
                    assert last_tx_block.foliage_transaction_block is not None
                    if (
                        self.config["testing"] is False
                        and last_tx_block.foliage_transaction_block.timestamp < int(time.time()) - 600
                    ):
                        # Full node not synced, don't sync to it
                        self.log.info("Peer we connected to is not fully synced, dropping connection...")
                        await peer.close()
                        return

                long_sync_threshold = 100
                far_behind: bool = (
                    peak.height - self.wallet_state_manager.blockchain.get_peak_height() > long_sync_threshold
                )
                fork_point = -1
                if current_peak is not None:
                    # Force a long sync if it's a very deep reorg
                    try:
                        fork_point = find_fork_point_in_chain(
                            self.wallet_state_manager.blockchain, peak_block, current_peak
                        )
                        if peak.height - fork_point > long_sync_threshold:
                            far_behind = True
                    except KeyError:
                        # If we don't have the blocks to find fork point, it's a deep reorg
                        far_behind = True

                # check if claimed peak is heavier or same as our current peak
                # if we haven't synced fully to this peer sync again
                if (
                    peer.peer_node_id not in self.synced_peers or far_behind
                ) and peak.height >= self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
                    syncing = False
                    if far_behind or len(self.synced_peers) == 0:
                        syncing = True
                        self.wallet_state_manager.set_sync_mode(True)
                    try:
                        (
                            valid_weight_proof,
                            weight_proof,
                            summaries,
                            block_records,
                        ) = await self.fetch_and_validate_the_weight_proof(peer, response.header_block)
                        if valid_weight_proof is False:
                            if syncing:
                                self.wallet_state_manager.set_sync_mode(False)
                            await peer.close()
                            return
                        assert weight_proof is not None
                        if syncing:
                            async with self.wallet_state_manager.lock:
                                await self.untrusted_sync_to_peer(peer, weight_proof, syncing, fork_point)
                        else:
                            await self.untrusted_sync_to_peer(peer, weight_proof, syncing, fork_point)
                        if (
                            self.wallet_state_manager.blockchain.synced_weight_proof is None
                            or weight_proof.recent_chain_data[-1].weight
                            > self.wallet_state_manager.blockchain.synced_weight_proof.recent_chain_data[-1].weight
                        ):
                            await self.wallet_state_manager.blockchain.new_weight_proof(weight_proof, block_records)

                        self.synced_peers.add(peer.peer_node_id)

                        self.wallet_state_manager.state_changed("new_block")
                        await self.update_ui()
                    except Exception:
                        if syncing:
                            self.wallet_state_manager.set_sync_mode(False)
                        tb = traceback.format_exc()
                        self.log.error(f"Error syncing to {peer.get_peer_info()} {tb}")
                        await peer.close()
                        return
                    if syncing:
                        self.wallet_state_manager.set_sync_mode(False)

                else:
                    if peer.peer_node_id not in self.synced_peers:
                        # Edge case, we still want to subscribe for all phs
                        # (Hints are not in filter)
                        await self.untrusted_subscribe_to_puzzle_hashes(peer, False, None, None)
                        self.synced_peers.add(peer.peer_node_id)
                    await self.wallet_short_sync_backtrack(peak_block, peer)
                    self.wallet_state_manager.set_sync_mode(False)
                    self.wallet_state_manager.state_changed("new_block")

        await self.wallet_state_manager.new_peak(peak)
        self._pending_tx_handler()

    async def wallet_short_sync_backtrack(self, header_block: HeaderBlock, peer):
        assert self.wallet_state_manager is not None

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

        blocks.reverse()
        # Roll back coins and transactions
        await self.wallet_state_manager.reorg_rollback(fork_height)
        peak = await self.wallet_state_manager.blockchain.get_peak_block()
        if peak is not None:
            assert header_block.weight >= peak.weight
        for block in blocks:
            # Set blockchain to the latest peak
            res, err = await self.wallet_state_manager.blockchain.receive_block(block)
            if res == ReceiveBlockResult.INVALID_BLOCK:
                raise ValueError(err)

        # Add new coins and transactions
        await self.complete_blocks(blocks, peer)

    async def complete_blocks(self, header_blocks: List[HeaderBlock], peer: WSChiaConnection):
        if self.wallet_state_manager is None:
            return None
        all_outgoing_per_wallet: Dict[int, List[TransactionRecord]] = {}

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

                for added_coin in added_coins:
                    self.log.info(f"coin added {added_coin}")
                    wallet_info = await self.wallet_state_manager.get_wallet_id_for_puzzle_hash(added_coin.puzzle_hash)
                    if wallet_info is None:
                        continue
                    wallet_id, wallet_type = wallet_info
                    if wallet_id in all_outgoing_per_wallet:
                        all_outgoing = all_outgoing_per_wallet[wallet_id]
                    else:
                        all_outgoing = await self.wallet_state_manager.tx_store.get_all_transactions_for_wallet(
                            wallet_id
                        )
                        all_outgoing_per_wallet[wallet_id] = all_outgoing
                    derivation_index = await self.wallet_state_manager.puzzle_store.index_for_puzzle_hash(
                        added_coin.puzzle_hash
                    )
                    if derivation_index is not None:
                        await self.wallet_state_manager.puzzle_store.set_used_up_to(derivation_index, False)
                    await self.wallet_state_manager.coin_added(
                        added_coin, block.height, all_outgoing, wallet_id, wallet_type
                    )

                all_unconfirmed: List[
                    TransactionRecord
                ] = await self.wallet_state_manager.tx_store.get_all_unconfirmed()

                all_removed_coins = None
                trade_removals = await self.wallet_state_manager.trade_manager.get_coins_of_interest()

                for removed_coin in removed_coins:
                    self.log.info(f"coin removed {removed_coin}")
                    if removed_coin.name() in trade_removals:
                        await self.wallet_state_manager.trade_manager.coins_of_interest_farmed(
                            CoinState(removed_coin, block.height, None)  # `None` is a lie but it shouldn't matter
                        )
                    for unconfirmed_record in all_unconfirmed:
                        if removed_coin in unconfirmed_record.removals:
                            self.log.info(f"Setting tx_id: {unconfirmed_record.name} to confirmed")
                            await self.wallet_state_manager.tx_store.set_confirmed(
                                unconfirmed_record.name, block.height
                            )

                    record = await self.wallet_state_manager.coin_store.get_coin_record(removed_coin.name())
                    if record is None:
                        continue
                    await self.wallet_state_manager.coin_store.set_spent(removed_coin.name(), block.height)
                    removed_record = await self.wallet_state_manager.coin_store.get_coin_record(removed_coin.name())

                    if removed_record is not None and removed_record.wallet_type == WalletType.POOLING_WALLET:
                        if all_removed_coins is None:
                            all_removed_coins = await self.get_removals(peer, block, added_coins, removals, True)
                        pool_spend = await self.fetch_puzzle_solution(peer, block.height, removed_coin)
                        if len(pool_spend.additions()) > 0:
                            pool_added_coin = pool_spend.additions()[0]
                            await self.wallet_state_manager.coin_added(
                                pool_added_coin,
                                block.height,
                                [],
                                uint32(removed_record.wallet_id),
                                removed_record.wallet_type,
                            )
                            pool_wallet = self.wallet_state_manager.wallets[uint32(removed_record.wallet_id)]
                            await pool_wallet.apply_state_transitions(pool_spend, block.height)
                            assert all_removed_coins is not None
                            if pool_added_coin in all_removed_coins:
                                pool_spend_2 = await self.fetch_puzzle_solution(peer, block.height, pool_added_coin)
                                if len(pool_spend_2.additions()) > 0:
                                    pool_added_coin_2 = pool_spend_2.additions()[0]
                                    await self.wallet_state_manager.coin_added(
                                        pool_added_coin_2,
                                        block.height,
                                        [],
                                        uint32(removed_record.wallet_id),
                                        removed_record.wallet_type,
                                    )
                                    pool_wallet = self.wallet_state_manager.wallets[uint32(removed_record.wallet_id)]
                                    await pool_wallet.apply_state_transitions(pool_spend_2, block.height)

                    # Check if we have created a pool wallet
                    children: List[CoinState] = await self.fetch_children(peer, removed_coin.name(), None)
                    for child in children:
                        if child.coin.puzzle_hash != SINGLETON_LAUNCHER_HASH:
                            continue
                        if await self.wallet_state_manager.have_a_pool_wallet_with_launched_id(child.coin.name()):
                            continue
                        if child.spent_height is None:
                            continue

                        launcher_spend: CoinSpend = await self.fetch_puzzle_solution(peer, block.height, child.coin)
                        pool_state = None
                        try:
                            pool_state = solution_to_pool_state(launcher_spend)
                        except Exception as e:
                            self.log.debug(f"Not a pool wallet launcher {e}")
                            continue
                        assert pool_state is not None
                        assert child.spent_height is not None
                        pool_wallet = await PoolWallet.create(
                            self.wallet_state_manager,
                            self.wallet_state_manager.main_wallet,
                            child.coin.name(),
                            [launcher_spend],
                            child.spent_height,
                            False,
                            "pool_wallet",
                        )
                        await pool_wallet.apply_state_transitions(launcher_spend, block.height)
                        pool_added_coin = launcher_spend.additions()[0]
                        await self.wallet_state_manager.coin_added(
                            pool_added_coin,
                            block.height,
                            [],
                            uint32(pool_wallet.wallet_id),
                            WalletType(pool_wallet.type()),
                        )

        await self.update_ui()

    async def update_ui(self):
        for wallet_id, wallet in self.wallet_state_manager.wallets.items():
            self.wallet_state_manager.state_changed("coin_removed", wallet_id)
            self.wallet_state_manager.state_changed("coin_added", wallet_id)

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
                validated = validate_additions(
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
                coin.puzzle_hash
            )
            if record_info is not None and record_info.wallet_type == WalletType.CAT:
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
                validated = validate_removals(
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

    async def fetch_and_validate_the_weight_proof(
        self, peer: WSChiaConnection, peak: HeaderBlock
    ) -> Tuple[bool, Optional[WeightProof], List[SubEpochSummary], List[BlockRecord]]:
        assert self.wallet_state_manager is not None
        assert self.wallet_state_manager.weight_proof_handler is not None

        weight_request = RequestProofOfWeight(peak.height, peak.header_hash)
        weight_proof_response: RespondProofOfWeight = await peer.request_proof_of_weight(weight_request, timeout=60)

        if weight_proof_response is None:
            return False, None, [], []
        start_validation = time.time()

        weight_proof = weight_proof_response.wp

        if weight_proof.recent_chain_data[-1].reward_chain_block.height != peak.height:
            return False, None, [], []
        if weight_proof.recent_chain_data[-1].reward_chain_block.weight != peak.weight:
            return False, None, [], []

        if weight_proof.get_hash() in self.valid_wp_cache:
            valid, fork_point, summaries, block_records = self.valid_wp_cache[weight_proof.get_hash()]
        else:
            start_validation = time.time()
            (
                valid,
                fork_point,
                summaries,
                block_records,
            ) = await self.wallet_state_manager.weight_proof_handler.validate_weight_proof(weight_proof)
            if valid:
                self.valid_wp_cache[weight_proof.get_hash()] = valid, fork_point, summaries, block_records

        end_validation = time.time()
        self.log.info(f"It took {end_validation - start_validation} time to validate the weight proof")
        return valid, weight_proof, summaries, block_records

    async def get_puzzle_hashes_to_subscribe(self) -> List[bytes32]:
        assert self.wallet_state_manager is not None
        all_puzzle_hashes = list(await self.wallet_state_manager.puzzle_store.get_all_puzzle_hashes())
        # Get all phs from interested store
        interested_puzzle_hashes = [
            t[0] for t in await self.wallet_state_manager.interested_store.get_interested_puzzle_hashes()
        ]
        all_puzzle_hashes.extend(interested_puzzle_hashes)
        return all_puzzle_hashes

    async def untrusted_subscribe_to_puzzle_hashes(
        self,
        peer: WSChiaConnection,
        save_state: bool,
        peer_request_cache: Optional[PeerRequestCache],
        weight_proof: Optional[WeightProof],
    ):
        assert self.wallet_state_manager is not None
        already_checked = set()
        continue_while = True
        while continue_while:
            all_puzzle_hashes = await self.get_puzzle_hashes_to_subscribe()
            to_check = []
            for ph in all_puzzle_hashes:
                if ph in already_checked:
                    continue
                else:
                    to_check.append(ph)
                    already_checked.add(ph)
                    if len(to_check) == 1000:
                        break
            msg = wallet_protocol.RegisterForPhUpdates(to_check, uint32(0))
            all_state: Optional[RespondToPhUpdates] = await peer.register_interest_in_puzzle_hash(msg)
            assert all_state is not None

            if save_state:
                assert weight_proof is not None
                assert peer_request_cache is not None
                validated_state = await self.validate_received_state_from_peer(
                    all_state.coin_states, peer, weight_proof, peer_request_cache, False
                )
                await self.wallet_state_manager.new_coin_state(validated_state, peer, weight_proof=weight_proof)

            # Check if new puzzle hashed have been created
            check_again = await self.get_puzzle_hashes_to_subscribe()

            continue_while = False
            for ph in check_again:
                if ph not in already_checked:
                    continue_while = True
                    break

    async def untrusted_sync_to_peer(
        self, peer: WSChiaConnection, weight_proof: WeightProof, syncing: bool, fork_height: int
    ):
        assert self.wallet_state_manager is not None
        # If new weight proof is higher than the old one, rollback to the fork point and than apply new coin_states
        if fork_height == -1:
            wp_fork_point = self.wallet_state_manager.weight_proof_handler.get_fork_point(
                old_wp=self.wallet_state_manager.blockchain.synced_weight_proof, new_wp=weight_proof
            )
            # Extra conservative
            fork_height = max(0, wp_fork_point - 10)
        self.log.info(f"Starting untrusted sync to: {peer.get_peer_info()}, syncing: {syncing}, fork at: {fork_height}")
        if syncing:
            self.log.info(f"Rollback for {fork_height}")
            await self.wallet_state_manager.reorg_rollback(fork_height)

        start_time: float = time.time()
        peer_request_cache: PeerRequestCache = PeerRequestCache()
        self.untrusted_caches[peer.peer_node_id] = peer_request_cache
        # Always sync fully from untrusted
        # Get state for puzzle hashes
        self.log.debug("Start untrusted_subscribe_to_puzzle_hashes  ")
        await self.untrusted_subscribe_to_puzzle_hashes(peer, True, peer_request_cache, weight_proof)
        self.log.debug("End untrusted_subscribe_to_puzzle_hashes  ")

        checked_call_coins = False
        checked_coins: Set[bytes32] = set()
        while not checked_call_coins:
            # Get state for coins ids
            all_coins = await self.wallet_state_manager.coin_store.get_coins_to_check(uint32(0))
            all_coin_names = [coin_record.name() for coin_record in all_coins]
            removed_dict = await self.wallet_state_manager.trade_manager.get_coins_of_interest()
            all_coin_names.extend(removed_dict.keys())

            to_check: List[bytes32] = []
            for coin_name in all_coin_names:
                if coin_name in checked_coins:
                    continue
                else:
                    to_check.append(coin_name)
                    checked_coins.add(coin_name)
                    if len(to_check) == 1000:
                        break

            msg1 = wallet_protocol.RegisterForCoinUpdates(to_check, uint32(0))
            new_state: Optional[RespondToCoinUpdates] = await peer.register_interest_in_coin(msg1)

            assert new_state is not None
            if syncing:
                # If syncing, completely change over to this peer's information
                coin_state_before_fork: List[CoinState] = new_state.coin_states
            else:
                # Otherwise, we only want to apply changes before the fork point, since we are synced to another peer
                # We are just validating that there is no missing information
                coin_state_before_fork = []
                for coin_state_entry in new_state.coin_states:
                    if coin_state_entry.spent_height is not None:
                        if coin_state_entry.spent_height <= fork_height:
                            coin_state_before_fork.append(coin_state_entry)
                    elif coin_state_entry.created_height is not None:
                        if coin_state_entry.created_height <= fork_height:
                            coin_state_before_fork.append(coin_state_entry)

            validated_state = await self.validate_received_state_from_peer(
                coin_state_before_fork, peer, weight_proof, peer_request_cache, False
            )
            # Apply validated state
            await self.wallet_state_manager.new_coin_state(validated_state, peer, weight_proof=weight_proof)

            all_coins = await self.wallet_state_manager.coin_store.get_coins_to_check(uint32(0))
            all_coin_names = [coin_record.name() for coin_record in all_coins]
            removed_dict = await self.wallet_state_manager.trade_manager.get_coins_of_interest()
            all_coin_names.extend(removed_dict.keys())

            checked_call_coins = True
            for coin_name in all_coin_names:
                if coin_name not in checked_coins:
                    checked_call_coins = False
                    break

        end_time = time.time()
        duration = end_time - start_time
        self.log.info(f"Sync duration was: {duration}")

    async def validate_received_state_from_peer(
        self,
        coin_states: List[CoinState],
        peer,
        weight_proof: WeightProof,
        peer_request_cache: PeerRequestCache,
        return_old_state: bool,
    ) -> List[CoinState]:
        """
        Returns all state that is valid and included in the blockchain proved by the weight proof. If return_old_states
        is False, only new states that are not in the coin_store are returned.
        """
        assert self.wallet_state_manager is not None
        all_validated_states = []
        total = len(coin_states)
        for coin_idx, coin_state in enumerate(coin_states):
            looked_up_coin: Optional[WalletCoinRecord] = await self.wallet_state_manager.coin_store.get_coin_record(
                coin_state.coin.name()
            )
            if (
                looked_up_coin is not None
                and coin_state.created_height is not None
                and looked_up_coin.confirmed_block_height == coin_state.created_height
            ):
                if looked_up_coin.spent:
                    if looked_up_coin.spent_block_height == coin_state.spent_height:
                        # Both are spent and created at same height, no need to validate
                        if return_old_state:
                            all_validated_states.append(coin_state)
                        continue
                else:
                    if coin_state.spent_height is None:
                        # Both are not spent, no need to validate
                        if return_old_state:
                            all_validated_states.append(coin_state)
                        continue
            if coin_state.get_hash() in peer_request_cache.states_validated:
                all_validated_states.append(coin_state)
                continue
            self.log.info(f"Validating {coin_idx + 1} of {total}")
            spent_height = coin_state.spent_height
            confirmed_height = coin_state.created_height

            current = await self.wallet_state_manager.coin_store.get_coin_record(coin_state.coin.name())
            # if remote state is same as current local state we skip validation

            # CoinRecord unspent = height 0, coin state = None. We adjust for comparison bellow
            current_spent_height = None
            if current is not None and current.spent_block_height != 0:
                current_spent_height = current.spent_block_height

            # It's possible that new state has been added before we finished validating weight proof
            # We'll just ignore it here, backward sync will pick it up
            wp_tip_height = weight_proof.recent_chain_data[-1].height
            if (confirmed_height is not None and confirmed_height > wp_tip_height) or (
                spent_height is not None and spent_height > wp_tip_height
            ):
                continue
            elif (
                current is not None
                and current_spent_height == spent_height
                and current.confirmed_block_height == confirmed_height
            ):
                all_validated_states.append(coin_state)
                continue
            else:
                # Full info validation
                if confirmed_height is None:
                    # We shouldn't receive state for non-existing coin unless we specifically ask for it
                    peer.close(9999)
                    raise ValueError("Should not receive state for non-existing coin")

                self.log.debug(f"Validating state: {coin_state}")
                # request header block for created height
                if confirmed_height in peer_request_cache.blocks:
                    state_block: HeaderBlock = peer_request_cache.blocks[confirmed_height]
                else:
                    request = RequestHeaderBlocks(confirmed_height, confirmed_height)
                    res = await peer.request_header_blocks(request)
                    state_block = res.header_blocks[0]
                    peer_request_cache.blocks[confirmed_height] = state_block

                # get proof of inclusion
                assert state_block.foliage_transaction_block is not None
                validate_additions_result = await request_and_validate_additions(
                    peer,
                    state_block.height,
                    state_block.header_hash,
                    coin_state.coin.puzzle_hash,
                    state_block.foliage_transaction_block.additions_root,
                )

                if validate_additions_result is False:
                    peer.close(9999)
                    raise ValueError(f"Addition did not validate: {state_block}, {coin_state}")

                # get blocks on top of this block

                validated = await self.validate_state(weight_proof, state_block, peer, peer_request_cache)
                if not validated:
                    raise ValueError("Validation failed")

                if spent_height is None and current is not None and current.spent_block_height != 0:
                    # Peer is telling us that coin that was previously known to be spent is not spent anymore
                    # Check old state
                    if spent_height in peer_request_cache.blocks:
                        spent_state_block: HeaderBlock = peer_request_cache.blocks[current.spent_block_height]
                    else:
                        request = RequestHeaderBlocks(current.spent_block_height, current.spent_block_height)
                        res = await peer.request_header_blocks(request)
                        spent_state_block = res.header_blocks[0]
                        assert spent_state_block.height == current.spent_block_height
                        peer_request_cache.blocks[current.spent_block_height] = spent_state_block
                    assert spent_state_block.foliage_transaction_block is not None
                    validate_removals_result: bool = await request_and_validate_removals(
                        peer,
                        current.spent_block_height,
                        spent_state_block.header_hash,
                        coin_state.coin.name(),
                        spent_state_block.foliage_transaction_block.removals_root,
                    )
                    if validate_removals_result is False:
                        peer.close(9999)
                        raise ValueError("Validation failed")
                    validated = await self.validate_state(weight_proof, spent_state_block, peer, peer_request_cache)
                    if not validated:
                        raise ValueError("Validation failed")

                if spent_height is not None:
                    # request header block for created height
                    if spent_height in peer_request_cache.blocks:
                        spent_state_block = peer_request_cache.blocks[spent_height]
                    else:
                        request = RequestHeaderBlocks(spent_height, spent_height)
                        res = await peer.request_header_blocks(request)
                        spent_state_block = res.header_blocks[0]
                        assert spent_state_block.height == spent_height
                        peer_request_cache.blocks[spent_height] = spent_state_block
                    assert spent_state_block.foliage_transaction_block is not None
                    validate_removals_result = await request_and_validate_removals(
                        peer,
                        spent_state_block.height,
                        spent_state_block.header_hash,
                        coin_state.coin.name(),
                        spent_state_block.foliage_transaction_block.removals_root,
                    )
                    if validate_removals_result is False:
                        peer.close(9999)
                        raise ValueError(f"Removals did not validate {spent_state_block}, {coin_state}")
                    validated = await self.validate_state(weight_proof, spent_state_block, peer, peer_request_cache)
                    if not validated:
                        raise ValueError("Validation failed")
                all_validated_states.append(coin_state)
            peer_request_cache.states_validated[coin_state.get_hash()] = coin_state
        return all_validated_states

    async def validate_state(
        self, weight_proof: WeightProof, block: HeaderBlock, peer, peer_request_cache: PeerRequestCache
    ) -> bool:
        assert self.wallet_state_manager is not None

        if block.height >= weight_proof.recent_chain_data[0].height:
            # this was already validated as part of the wp validation
            index = block.height - weight_proof.recent_chain_data[0].height
            if weight_proof.recent_chain_data[index].header_hash != block.header_hash:
                self.log.error("Failed validation 1")
                return False
            return True
        else:
            start = block.height + 1
            compare_to_recent = False
            current_ses: Optional[SubEpochData] = None
            inserted: Optional[SubEpochData] = None
            first_height_recent = weight_proof.recent_chain_data[0].height
            if start > first_height_recent - 1000:
                compare_to_recent = True
                end = first_height_recent
            else:
                request = RequestSESInfo(block.height, block.height + 32)
                if request.get_hash() in peer_request_cache.ses_requests:
                    res_ses: RespondSESInfo = peer_request_cache.ses_requests[request.get_hash()]
                else:
                    res_ses = await peer.request_ses_hashes(request)
                ses_0 = res_ses.reward_chain_hash[0]
                last_height = res_ses.heights[0][-1]  # Last height in sub epoch
                end = last_height
                for idx, ses in enumerate(weight_proof.sub_epochs):
                    if idx > len(weight_proof.sub_epochs) - 3:
                        break
                    if ses.reward_chain_hash == ses_0:
                        current_ses = ses
                        inserted = weight_proof.sub_epochs[idx + 2]
                        break
                if current_ses is None:
                    self.log.error("Failed validation 2")
                    return False

            blocks = []

            for i in range(start - (start % 32), end + 1, 32):
                request_start = min(uint32(i), end)
                request_end = min(uint32(i + 31), end)
                request_h_response = RequestHeaderBlocks(request_start, request_end)
                if request_h_response.get_hash() in peer_request_cache.block_requests:
                    res_h_blocks: RespondHeaderBlocks = peer_request_cache.block_requests[request_h_response.get_hash()]
                else:
                    res_h_blocks = await peer.request_header_blocks(request_h_response)
                    peer_request_cache.block_requests[request_h_response.get_hash()] = res_h_blocks
                self.log.info(f"Fetching blocks: {request_start} - {request_end}")
                blocks.extend([bl for bl in res_h_blocks.header_blocks if bl.height >= start])

            if compare_to_recent and weight_proof.recent_chain_data[0].header_hash != blocks[-1].header_hash:
                self.log.error("Failed validation 3")
                return False

            reversed_blocks = blocks.copy()
            reversed_blocks.reverse()

            if not compare_to_recent:
                last = reversed_blocks[0].finished_sub_slots[-1].reward_chain.get_hash()
                if inserted is None or last != inserted.reward_chain_hash:
                    self.log.error("Failed validation 4")
                    return False

            for idx, en_block in enumerate(reversed_blocks):
                if idx == len(reversed_blocks) - 1:
                    next_block_rc_hash = block.reward_chain_block.get_hash()
                    prev_hash = block.header_hash
                else:
                    next_block_rc_hash = reversed_blocks[idx + 1].reward_chain_block.get_hash()
                    prev_hash = reversed_blocks[idx + 1].header_hash

                if not en_block.prev_header_hash == prev_hash:
                    self.log.error("Failed validation 5")
                    return False

                if len(en_block.finished_sub_slots) > 0:
                    #  What to do here
                    reversed_slots = en_block.finished_sub_slots.copy()
                    reversed_slots.reverse()
                    for slot_idx, slot in enumerate(reversed_slots[:-1]):
                        hash_val = reversed_slots[slot_idx + 1].reward_chain.get_hash()
                        if not hash_val == slot.reward_chain.end_of_slot_vdf.challenge:
                            self.log.error("Failed validation 6")
                            return False
                    if not next_block_rc_hash == reversed_slots[-1].reward_chain.end_of_slot_vdf.challenge:
                        self.log.error("Failed validation 7")
                        return False
                else:
                    if not next_block_rc_hash == en_block.reward_chain_block.reward_chain_ip_vdf.challenge:
                        self.log.error("Failed validation 8")
                        return False

                if idx > len(reversed_blocks) - 50:
                    if not AugSchemeMPL.verify(
                        en_block.reward_chain_block.proof_of_space.plot_public_key,
                        en_block.foliage.foliage_block_data.get_hash(),
                        en_block.foliage.foliage_block_data_signature,
                    ):
                        self.log.error("Failed validation 9")
                        return False
            return True

    async def fetch_puzzle_solution(self, peer, height: uint32, coin: Coin) -> CoinSpend:
        solution_response = await peer.request_puzzle_solution(
            wallet_protocol.RequestPuzzleSolution(coin.name(), height)
        )
        if solution_response is None or not isinstance(solution_response, wallet_protocol.RespondPuzzleSolution):
            raise ValueError(f"Was not able to obtain solution {solution_response}")
        assert solution_response.response.puzzle.get_tree_hash() == coin.puzzle_hash
        assert solution_response.response.coin_name == coin.name()

        return CoinSpend(
            coin,
            solution_response.response.puzzle.to_serialized_program(),
            solution_response.response.solution.to_serialized_program(),
        )

    async def fetch_children_and_validate(
        self, peer, coin_name, weight_proof: Optional[WeightProof]
    ) -> List[CoinState]:
        response: Optional[wallet_protocol.RespondChildren] = await peer.request_children(
            wallet_protocol.RequestChildren(coin_name)
        )
        if response is None or not isinstance(response, wallet_protocol.RespondChildren):
            raise ValueError(f"Was not able to obtain children {response}")
        if not self.is_trusted(peer):
            if peer.peer_node_id in self.untrusted_caches:
                request_cache = self.untrusted_caches[peer.peer_node_id]
            else:
                request_cache = PeerRequestCache()
            assert weight_proof is not None
            validated_states = await self.validate_received_state_from_peer(
                response.coin_states, peer, weight_proof, request_cache, True
            )
            return validated_states

        return response.coin_states

    async def fetch_children(self, peer, coin_name, weight_proof: Optional[WeightProof]) -> List[CoinState]:
        response: Optional[wallet_protocol.RespondChildren] = await peer.request_children(
            wallet_protocol.RequestChildren(coin_name)
        )
        if response is None or not isinstance(response, wallet_protocol.RespondChildren):
            raise ValueError(f"Was not able to obtain children {response}")

        return response.coin_states
