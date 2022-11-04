import asyncio
import dataclasses
import logging
import multiprocessing
import random
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

from blspy import AugSchemeMPL, PrivateKey, G2Element, G1Element
from packaging.version import Version

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain import ReceiveBlockResult
from chia.consensus.constants import ConsensusConstants
from chia.daemon.keychain_proxy import (
    KeychainProxy,
    connect_to_keychain_and_validate,
    wrap_local_keychain,
)
from chia.protocols import wallet_protocol
from chia.protocols.full_node_protocol import RequestProofOfWeight, RespondProofOfWeight
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import (
    CoinState,
    RespondBlockHeader,
    RespondToCoinUpdates,
    RespondToPhUpdates,
)
from chia.rpc.rpc_server import default_get_connections
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
from chia.types.weight_proof import WeightProof
from chia.util.chunks import chunks
from chia.util.config import WALLET_PEERS_PATH_KEY_DEPRECATED, process_config_start_method
from chia.util.errors import KeychainIsLocked, KeychainProxyConnectionFailure, KeychainIsEmpty, KeychainKeyNotFound
from chia.util.ints import uint32, uint64
from chia.util.keychain import Keychain
from chia.util.path import path_from_root
from chia.util.profiler import profile_task
from chia.util.memory_profiler import mem_profile_task
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.new_peak_queue import NewPeakItem, NewPeakQueue, NewPeakQueueTypes
from chia.wallet.util.peer_request_cache import PeerRequestCache, can_use_peer_request_cache
from chia.wallet.util.wallet_sync_utils import (
    fetch_header_blocks_in_range,
    fetch_last_tx_from_peer,
    last_change_height_cs,
    PeerRequestException,
    request_and_validate_additions,
    request_and_validate_removals,
    request_header_blocks,
    subscribe_to_coin_updates,
    subscribe_to_phs,
)
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.wallet.wallet_weight_proof_handler import get_wp_fork_point, WalletWeightProofHandler


def get_wallet_db_path(root_path: Path, config: Dict[str, Any], key_fingerprint: str) -> Path:
    """
    Construct a path to the wallet db. Uses config values and the wallet key's fingerprint to
    determine the wallet db filename.
    """
    db_path_replaced: str = (
        config["database_path"].replace("CHALLENGE", config["selected_network"]).replace("KEY", key_fingerprint)
    )

    # "v2_r1" is the current wallet db version identifier
    if "v2_r1" not in db_path_replaced:
        db_path_replaced = db_path_replaced.replace("v2", "v2_r1").replace("v1", "v2_r1")

    path: Path = path_from_root(root_path, db_path_replaced)
    return path


@dataclasses.dataclass
class WalletNode:
    config: Dict
    root_path: Path
    constants: ConsensusConstants
    local_keychain: Optional[Keychain] = None

    log: logging.Logger = logging.getLogger(__name__)

    # Normal operation data
    cached_blocks: Dict = dataclasses.field(default_factory=dict)
    future_block_hashes: Dict = dataclasses.field(default_factory=dict)

    # Sync data
    proof_hashes: List = dataclasses.field(default_factory=list)
    state_changed_callback: Optional[Callable] = None
    _wallet_state_manager: Optional[WalletStateManager] = None
    _weight_proof_handler: Optional[WalletWeightProofHandler] = None
    _server: Optional[ChiaServer] = None
    wsm_close_task: Optional[asyncio.Task] = None
    sync_task: Optional[asyncio.Task] = None
    logged_in_fingerprint: Optional[int] = None
    peer_task: Optional[asyncio.Task] = None
    logged_in: bool = False
    _keychain_proxy: Optional[KeychainProxy] = None
    height_to_time: Dict[uint32, uint64] = dataclasses.field(default_factory=dict)
    # Peers that we have long synced to
    synced_peers: Set[bytes32] = dataclasses.field(default_factory=set)
    wallet_peers: Optional[WalletPeers] = None
    wallet_peers_initialized: bool = False
    valid_wp_cache: Dict[bytes32, Any] = dataclasses.field(default_factory=dict)
    untrusted_caches: Dict[bytes32, PeerRequestCache] = dataclasses.field(default_factory=dict)
    # in Untrusted mode wallet might get the state update before receiving the block
    race_cache: Dict[bytes32, Set[CoinState]] = dataclasses.field(default_factory=dict)
    race_cache_hashes: List[Tuple[uint32, bytes32]] = dataclasses.field(default_factory=list)
    node_peaks: Dict[bytes32, Tuple[uint32, bytes32]] = dataclasses.field(default_factory=dict)
    validation_semaphore: Optional[asyncio.Semaphore] = None
    local_node_synced: bool = False
    LONG_SYNC_THRESHOLD: int = 300
    last_wallet_tx_resend_time: int = 0
    # Duration in seconds
    wallet_tx_resend_timeout_secs: int = 1800
    _new_peak_queue: Optional[NewPeakQueue] = None
    full_node_peer: Optional[PeerInfo] = None

    _shut_down: bool = False
    _process_new_subscriptions_task: Optional[asyncio.Task] = None
    _retry_failed_states_task: Optional[asyncio.Task] = None
    _primary_peer_sync_task: Optional[asyncio.Task] = None
    _secondary_peer_sync_task: Optional[asyncio.Task] = None

    @property
    def keychain_proxy(self) -> KeychainProxy:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._keychain_proxy is None:
            raise RuntimeError("keychain proxy not assigned")

        return self._keychain_proxy

    @property
    def wallet_state_manager(self) -> WalletStateManager:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._wallet_state_manager is None:
            raise RuntimeError("wallet state manager not assigned")

        return self._wallet_state_manager

    @property
    def server(self) -> ChiaServer:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._server is None:
            raise RuntimeError("server not assigned")

        return self._server

    @property
    def new_peak_queue(self) -> NewPeakQueue:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._new_peak_queue is None:
            raise RuntimeError("new peak queue not assigned")

        return self._new_peak_queue

    def get_connections(self, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

    async def ensure_keychain_proxy(self) -> KeychainProxy:
        if self._keychain_proxy is None:
            if self.local_keychain:
                self._keychain_proxy = wrap_local_keychain(self.local_keychain, log=self.log)
            else:
                self._keychain_proxy = await connect_to_keychain_and_validate(self.root_path, self.log)
                if not self._keychain_proxy:
                    raise KeychainProxyConnectionFailure()
        return self._keychain_proxy

    def get_cache_for_peer(self, peer) -> PeerRequestCache:
        if peer.peer_node_id not in self.untrusted_caches:
            self.untrusted_caches[peer.peer_node_id] = PeerRequestCache()
        return self.untrusted_caches[peer.peer_node_id]

    def rollback_request_caches(self, reorg_height: int):
        # Everything after reorg_height should be removed from the cache
        for cache in self.untrusted_caches.values():
            cache.clear_after_height(reorg_height)

    async def get_key_for_fingerprint(self, fingerprint: Optional[int]) -> Optional[PrivateKey]:
        try:
            keychain_proxy = await self.ensure_keychain_proxy()
            # Returns first private key if fingerprint is None
            key = await keychain_proxy.get_key_for_fingerprint(fingerprint)
        except KeychainIsEmpty:
            self.log.warning("No keys present. Create keys with the UI, or with the 'chia keys' program.")
            return None
        except KeychainKeyNotFound:
            self.log.warning(f"Key not found for fingerprint {fingerprint}")
            return None
        except KeychainIsLocked:
            self.log.warning("Keyring is locked")
            return None
        except KeychainProxyConnectionFailure as e:
            tb = traceback.format_exc()
            self.log.error(f"Missing keychain_proxy: {e} {tb}")
            raise  # Re-raise so that the caller can decide whether to continue or abort

        return key

    async def get_private_key(self, fingerprint: Optional[int]) -> Optional[PrivateKey]:
        """
        Attempt to get the private key for the given fingerprint. If the fingerprint is None,
        get_key_for_fingerprint() will return the first private key. Similarly, if a key isn't
        returned for the provided fingerprint, the first key will be returned.
        """
        key: Optional[PrivateKey] = await self.get_key_for_fingerprint(fingerprint)

        if key is None and fingerprint is not None:
            key = await self.get_key_for_fingerprint(None)
            if key is not None:
                self.log.info(f"Using first key found (fingerprint: {key.get_g1().get_fingerprint()})")

        return key

    async def _start(self) -> None:
        await self._start_with_fingerprint()

    async def _start_with_fingerprint(
        self,
        fingerprint: Optional[int] = None,
    ) -> bool:
        # Makes sure the coin_state_updates get higher priority than new_peak messages.
        # Delayed instantiation until here to avoid errors.
        #   got Future <Future pending> attached to a different loop
        self._new_peak_queue = NewPeakQueue(inner_queue=asyncio.PriorityQueue())

        multiprocessing_start_method = process_config_start_method(config=self.config, log=self.log)
        multiprocessing_context = multiprocessing.get_context(method=multiprocessing_start_method)
        self._weight_proof_handler = WalletWeightProofHandler(self.constants, multiprocessing_context)
        self.synced_peers = set()
        private_key = await self.get_private_key(fingerprint or self.get_last_used_fingerprint())
        if private_key is None:
            self.log_out()
            return False

        if self.config.get("enable_profiler", False):
            if sys.getprofile() is not None:
                self.log.warning("not enabling profiler, getprofile() is already set")
            else:
                asyncio.create_task(profile_task(self.root_path, "wallet", self.log))

        if self.config.get("enable_memory_profiler", False):
            asyncio.create_task(mem_profile_task(self.root_path, "wallet", self.log))

        path: Path = get_wallet_db_path(self.root_path, self.config, str(private_key.get_g1().get_fingerprint()))
        path.parent.mkdir(parents=True, exist_ok=True)

        self._wallet_state_manager = await WalletStateManager.create(
            private_key,
            self.config,
            path,
            self.constants,
            self.server,
            self.root_path,
            self,
        )

        assert self._wallet_state_manager is not None
        if self._wallet_state_manager.blockchain.synced_weight_proof is not None:
            weight_proof = self._wallet_state_manager.blockchain.synced_weight_proof
            success, _, records = await self._weight_proof_handler.validate_weight_proof(weight_proof, True)
            assert success is True and records is not None and len(records) > 1
            await self._wallet_state_manager.blockchain.new_valid_weight_proof(weight_proof, records)

        if self.wallet_peers is None:
            self.initialize_wallet_peers()

        if self.state_changed_callback is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)

        self.last_wallet_tx_resend_time = int(time.time())
        self.last_state_retry_time = int(time.time())
        self.wallet_tx_resend_timeout_secs = self.config.get("tx_resend_timeout_secs", 60 * 60)
        self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)
        self._shut_down = False
        self._process_new_subscriptions_task = asyncio.create_task(self._process_new_subscriptions())
        self._retry_failed_states_task = asyncio.create_task(self._retry_failed_states())

        self.sync_event = asyncio.Event()
        self.log_in(private_key)
        self.wallet_state_manager.set_sync_mode(False)

        async with self.wallet_state_manager.puzzle_store.lock:
            index = await self.wallet_state_manager.puzzle_store.get_last_derivation_path()
            if index is None or index < self.wallet_state_manager.initial_num_public_keys - 1:
                await self.wallet_state_manager.create_more_puzzle_hashes(from_zero=True)
                self.wsm_close_task = None
        return True

    def _close(self):
        self.log.info("self._close")
        self.log_out()
        self._shut_down = True
        if self._weight_proof_handler is not None:
            self._weight_proof_handler.cancel_weight_proof_tasks()
        if self._process_new_subscriptions_task is not None:
            self._process_new_subscriptions_task.cancel()
        if self._retry_failed_states_task is not None:
            self._retry_failed_states_task.cancel()
        if self._primary_peer_sync_task is not None:
            self._primary_peer_sync_task.cancel()
        if self._secondary_peer_sync_task is not None:
            self._secondary_peer_sync_task.cancel()

    async def _await_closed(self, shutting_down: bool = True):
        self.log.info("self._await_closed")
        if self._server is not None:
            await self.server.close_all_connections()
        if self.wallet_peers is not None:
            await self.wallet_peers.ensure_is_closed()
        if self._wallet_state_manager is not None:
            await self.wallet_state_manager._await_closed()
            self._wallet_state_manager = None
        if shutting_down and self._keychain_proxy is not None:
            proxy = self._keychain_proxy
            self._keychain_proxy = None
            await proxy.close()
            await asyncio.sleep(0.5)  # https://docs.aiohttp.org/en/stable/client_advanced.html#graceful-shutdown
        self.wallet_peers = None

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

        if self._wallet_state_manager is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)
            self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)

    def _pending_tx_handler(self):
        if self._wallet_state_manager is None:
            return None
        asyncio.create_task(self._resend_queue())

    async def _resend_queue(self):
        if self._shut_down or self._server is None or self._wallet_state_manager is None:
            return None

        for msg, sent_peers in await self._messages_to_resend():
            if self._shut_down or self._server is None or self._wallet_state_manager is None:
                return None
            full_nodes = self.server.get_connections(NodeType.FULL_NODE)
            for peer in full_nodes:
                if peer.peer_node_id in sent_peers:
                    continue
                self.log.debug(f"sending: {msg}")
                await peer.send_message(msg)

    async def _messages_to_resend(self) -> List[Tuple[Message, Set[bytes32]]]:
        if self._wallet_state_manager is None or self._shut_down:
            return []
        messages: List[Tuple[Message, Set[bytes32]]] = []

        current_time = int(time.time())
        retry_accepted_txs = False
        if self.last_wallet_tx_resend_time < current_time - self.wallet_tx_resend_timeout_secs:
            self.last_wallet_tx_resend_time = current_time
            retry_accepted_txs = True
        records: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_not_sent(
            include_accepted_txs=retry_accepted_txs
        )

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

    async def _retry_failed_states(self):
        while not self._shut_down:
            try:
                await asyncio.sleep(5)
                current_time = time.time()
                if self.last_state_retry_time < current_time - 10:
                    self.last_state_retry_time = current_time
                    if self.wallet_state_manager is None:
                        continue
                    states_to_retry = await self.wallet_state_manager.retry_store.get_all_states_to_retry()
                    for state, peer_id, fork_height in states_to_retry:
                        matching_peer = tuple(
                            p for p in self.server.get_connections(NodeType.FULL_NODE) if p.peer_node_id == peer_id
                        )
                        if len(matching_peer) == 0:
                            peer = self.get_full_node_peer()
                            if peer is None:
                                self.log.info(f"disconnected from all peers, cannot retry state: {state}")
                                continue
                            else:
                                self.log.info(
                                    f"disconnected from peer {peer_id}, state will retry with {peer.peer_node_id}"
                                )
                        else:
                            peer = matching_peer[0]
                        async with self.wallet_state_manager.db_wrapper.writer():
                            self.log.info(f"retrying coin_state: {state}")
                            try:
                                await self.wallet_state_manager.new_coin_state(
                                    [state], peer, None if fork_height == 0 else fork_height
                                )
                            except Exception as e:
                                self.log.exception(f"Exception while adding states.. : {e}")
                            else:
                                await self.wallet_state_manager.blockchain.clean_block_records()
            except asyncio.CancelledError:
                self.log.info("Retry task cancelled, exiting.")
                raise

    async def _process_new_subscriptions(self):
        while not self._shut_down:
            # Here we process four types of messages in the queue, where the first one has higher priority (lower
            # number in the queue), and priority decreases for each type.
            peer: Optional[WSChiaConnection] = None
            item: Optional[NewPeakItem] = None
            try:
                peer, item = None, None
                item = await self.new_peak_queue.get()
                self.log.debug("Pulled from queue: %s", item)
                assert item is not None
                if item.item_type == NewPeakQueueTypes.COIN_ID_SUBSCRIPTION:
                    # Subscriptions are the highest priority, because we don't want to process any more peaks or
                    # state updates until we are sure that we subscribed to everything that we need to. Otherwise,
                    # we might not be able to process some state.
                    coin_ids: List[bytes32] = item.data
                    for peer in self.server.get_connections(NodeType.FULL_NODE):
                        coin_states: List[CoinState] = await subscribe_to_coin_updates(coin_ids, peer, uint32(0))
                        if len(coin_states) > 0:
                            async with self.wallet_state_manager.lock:
                                await self.receive_state_from_peer(coin_states, peer)
                elif item.item_type == NewPeakQueueTypes.PUZZLE_HASH_SUBSCRIPTION:
                    puzzle_hashes: List[bytes32] = item.data
                    for peer in self.server.get_connections(NodeType.FULL_NODE):
                        # Puzzle hash subscription
                        coin_states: List[CoinState] = await subscribe_to_phs(puzzle_hashes, peer, uint32(0))
                        if len(coin_states) > 0:
                            async with self.wallet_state_manager.lock:
                                await self.receive_state_from_peer(coin_states, peer)
                elif item.item_type == NewPeakQueueTypes.FULL_NODE_STATE_UPDATED:
                    # Note: this can take a while when we have a lot of transactions. We want to process these
                    # before new_peaks, since new_peak_wallet requires that we first obtain the state for that peak.
                    request: wallet_protocol.CoinStateUpdate = item.data[0]
                    peer = item.data[1]
                    assert peer is not None
                    await self.state_update_received(request, peer)
                elif item.item_type == NewPeakQueueTypes.NEW_PEAK_WALLET:
                    # This can take a VERY long time, because it might trigger a long sync. It is OK if we miss some
                    # subscriptions or state updates, since all subscriptions and state updates will be handled by
                    # long_sync (up to the target height).
                    request: wallet_protocol.NewPeakWallet = item.data[0]
                    peer = item.data[1]
                    assert peer is not None
                    await self.new_peak_wallet(request, peer)
                else:
                    assert False
            except asyncio.CancelledError:
                self.log.info("Queue task cancelled, exiting.")
                raise
            except Exception as e:
                self.log.error(f"Exception handling {item}, {e} {traceback.format_exc()}")
                if peer is not None:
                    await peer.close(9999)

    def log_in(self, sk: PrivateKey):
        self.logged_in_fingerprint = sk.get_g1().get_fingerprint()
        self.logged_in = True
        self.log.info(f"Wallet is logged in using key with fingerprint: {self.logged_in_fingerprint}")
        try:
            self.update_last_used_fingerprint()
        except Exception:
            self.log.exception("Non-fatal: Unable to update last used fingerprint.")

    def log_out(self):
        self.logged_in_fingerprint = None
        self.logged_in = False

    def update_last_used_fingerprint(self) -> None:
        fingerprint = self.logged_in_fingerprint
        assert fingerprint is not None
        path = self.get_last_used_fingerprint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(fingerprint))
        self.log.info(f"Updated last used fingerprint: {fingerprint}")

    def get_last_used_fingerprint(self) -> Optional[int]:
        fingerprint: Optional[int] = None
        try:
            path = self.get_last_used_fingerprint_path()
            if path.exists():
                fingerprint = int(path.read_text().strip())
        except Exception:
            self.log.exception("Non-fatal: Unable to read last used fingerprint.")
        return fingerprint

    def get_last_used_fingerprint_path(self) -> Path:
        db_path: Path = path_from_root(self.root_path, self.config["database_path"])
        fingerprint_path = db_path.parent / "last_used_fingerprint"
        return fingerprint_path

    def set_server(self, server: ChiaServer):
        self._server = server
        self.initialize_wallet_peers()

    def initialize_wallet_peers(self):
        self.server.on_connect = self.on_connect
        network_name = self.config["selected_network"]

        connect_to_unknown_peers = self.config.get("connect_to_unknown_peers", True)
        testing = self.config.get("testing", False)
        if self.wallet_peers is None and connect_to_unknown_peers and not testing:
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
                self.config.get("dns_servers", ["dns-introducer.chia.net"]),
                self.config["peer_connect_interval"],
                network_name,
                None,
                self.log,
            )
            asyncio.create_task(self.wallet_peers.start())

    def on_disconnect(self, peer: WSChiaConnection):
        if self.is_trusted(peer):
            self.local_node_synced = False
            self.initialize_wallet_peers()

        if peer.peer_node_id in self.untrusted_caches:
            self.untrusted_caches.pop(peer.peer_node_id)
        if peer.peer_node_id in self.synced_peers:
            self.synced_peers.remove(peer.peer_node_id)
        if peer.peer_node_id in self.node_peaks:
            self.node_peaks.pop(peer.peer_node_id)

    async def on_connect(self, peer: WSChiaConnection):
        if self._wallet_state_manager is None:
            return None

        if Version(peer.protocol_version) < Version("0.0.33"):
            self.log.info("Disconnecting, full node running old software")
            await peer.close()

        trusted = self.is_trusted(peer)
        if not trusted and self.local_node_synced:
            await peer.close()

        if peer.peer_node_id in self.synced_peers:
            self.synced_peers.remove(peer.peer_node_id)

        self.log.info(f"Connected peer {peer.get_peer_info()} is trusted: {trusted}")
        messages_peer_ids = await self._messages_to_resend()
        self.wallet_state_manager.state_changed("add_connection")
        for msg, peer_ids in messages_peer_ids:
            if peer.peer_node_id in peer_ids:
                continue
            await peer.send_message(msg)

        if self.wallet_peers is not None:
            await self.wallet_peers.on_connect(peer)

    async def perform_atomic_rollback(self, fork_height: int, cache: Optional[PeerRequestCache] = None):
        self.log.info(f"perform_atomic_rollback to {fork_height}")
        # this is to start a write transaction
        async with self.wallet_state_manager.db_wrapper.writer():
            try:
                removed_wallet_ids = await self.wallet_state_manager.reorg_rollback(fork_height)
                await self.wallet_state_manager.blockchain.set_finished_sync_up_to(fork_height, in_rollback=True)
                if cache is None:
                    self.rollback_request_caches(fork_height)
                else:
                    cache.clear_after_height(fork_height)
            except Exception as e:
                tb = traceback.format_exc()
                self.log.error(f"Exception while perform_atomic_rollback: {e} {tb}")
                raise
            else:
                await self.wallet_state_manager.blockchain.clean_block_records()

                for wallet_id in removed_wallet_ids:
                    self.wallet_state_manager.wallets.pop(wallet_id)

        # this has to be called *after* the transaction commits, otherwise it
        # won't see the changes (since we spawn a new task to handle potential
        # resends)
        self._pending_tx_handler()

    async def long_sync(
        self,
        target_height: uint32,
        full_node: WSChiaConnection,
        fork_height: int,
        *,
        rollback: bool,
    ):
        """
        Sync algorithm:
        - Download and verify weight proof (if not trusted)
        - Roll back anything after the fork point (if rollback=True)
        - Subscribe to all puzzle_hashes over and over until there are no more updates
        - Subscribe to all coin_ids over and over until there are no more updates
        - rollback=False means that we are just double-checking with this peer to make sure we don't have any
          missing transactions, so we don't need to rollback
        """

        def is_new_state_update(cs: CoinState) -> bool:
            if cs.spent_height is None and cs.created_height is None:
                return True
            if cs.spent_height is not None and cs.spent_height >= fork_height:
                return True
            if cs.created_height is not None and cs.created_height >= fork_height:
                return True
            return False

        trusted: bool = self.is_trusted(full_node)
        self.log.info(f"Starting sync trusted: {trusted} to peer {full_node.peer_host}")
        start_time = time.time()

        if rollback:
            # we should clear all peers since this is a full rollback
            await self.perform_atomic_rollback(fork_height)
            await self.update_ui()

        # We only process new state updates to avoid slow reprocessing. We set the sync height after adding
        # Things, so we don't have to reprocess these later. There can be many things in ph_update_res.
        already_checked_ph: Set[bytes32] = set()
        continue_while: bool = True
        all_puzzle_hashes: List[bytes32] = await self.get_puzzle_hashes_to_subscribe()
        while continue_while:
            # Get all phs from puzzle store
            ph_chunks: Iterator[List[bytes32]] = chunks(all_puzzle_hashes, 1000)
            for chunk in ph_chunks:
                ph_update_res: List[CoinState] = await subscribe_to_phs(
                    [p for p in chunk if p not in already_checked_ph], full_node, 0
                )
                ph_update_res = list(filter(is_new_state_update, ph_update_res))
                if not await self.receive_state_from_peer(ph_update_res, full_node, update_finished_height=True):
                    # If something goes wrong, abort sync
                    return
                already_checked_ph.update(chunk)

            # Check if new puzzle hashed have been created
            await self.wallet_state_manager.create_more_puzzle_hashes()
            all_puzzle_hashes = await self.get_puzzle_hashes_to_subscribe()
            continue_while = False
            for ph in all_puzzle_hashes:
                if ph not in already_checked_ph:
                    continue_while = True
                    break
        self.log.info(f"Successfully subscribed and updated {len(already_checked_ph)} puzzle hashes")

        # The number of coin id updates are usually going to be significantly less than ph updates, so we can
        # sync from 0 every time.
        continue_while = True
        all_coin_ids: List[bytes32] = await self.get_coin_ids_to_subscribe(0)
        already_checked_coin_ids: Set[bytes32] = set()
        while continue_while:
            one_k_chunks = chunks(all_coin_ids, 1000)
            for chunk in one_k_chunks:
                c_update_res: List[CoinState] = await subscribe_to_coin_updates(chunk, full_node, 0)

                if not await self.receive_state_from_peer(c_update_res, full_node):
                    # If something goes wrong, abort sync
                    return
                already_checked_coin_ids.update(chunk)

            all_coin_ids = await self.get_coin_ids_to_subscribe(0)
            continue_while = False
            for coin_id in all_coin_ids:
                if coin_id not in already_checked_coin_ids:
                    continue_while = True
                    break
        self.log.info(f"Successfully subscribed and updated {len(already_checked_coin_ids)} coin ids")

        # Only update this fully when the entire sync has completed
        await self.wallet_state_manager.blockchain.set_finished_sync_up_to(target_height)

        if trusted:
            self.local_node_synced = True

        self.wallet_state_manager.state_changed("new_block")

        self.synced_peers.add(full_node.peer_node_id)
        await self.update_ui()

        end_time = time.time()
        duration = end_time - start_time
        self.log.info(f"Sync (trusted: {trusted}) duration was: {duration}")

    async def receive_state_from_peer(
        self,
        items_input: List[CoinState],
        peer: WSChiaConnection,
        fork_height: Optional[uint32] = None,
        height: Optional[uint32] = None,
        header_hash: Optional[bytes32] = None,
        update_finished_height: bool = False,
    ) -> bool:
        # Adds the state to the wallet state manager. If the peer is trusted, we do not validate. If the peer is
        # untrusted we do, but we might not add the state, since we need to receive the new_peak message as well.
        assert self._wallet_state_manager is not None
        trusted = self.is_trusted(peer)
        # Validate states in parallel, apply serial
        # TODO: optimize fetching
        if self.validation_semaphore is None:
            self.validation_semaphore = asyncio.Semaphore(10)

        # Rollback is handled in wallet_short_sync_backtrack for untrusted peers, so we don't need to do it here.
        # Also it's not safe to rollback, an untrusted peer can give us old fork point and make our TX disappear.
        # wallet_short_sync_backtrack can safely rollback because we validated the weight for the new peak so we
        # know the peer is telling the truth about the reorg.

        # If there is a fork, we need to ensure that we roll back in trusted mode to properly handle reorgs
        cache: PeerRequestCache = self.get_cache_for_peer(peer)

        if (
            trusted
            and fork_height is not None
            and height is not None
            and fork_height != height - 1
            and peer.peer_node_id in self.synced_peers
        ):
            # only one peer told us to rollback so only clear for that peer
            await self.perform_atomic_rollback(fork_height, cache=cache)
        else:
            if fork_height is not None:
                # only one peer told us to rollback so only clear for that peer
                cache.clear_after_height(fork_height)
                self.log.info(f"clear_after_height {fork_height} for peer {peer}")

        all_tasks: List[asyncio.Task] = []
        target_concurrent_tasks: int = 30
        concurrent_tasks_cs_heights: List[uint32] = []

        # Ensure the list is sorted

        before = len(items_input)
        items = await self.wallet_state_manager.filter_spam(list(sorted(items_input, key=last_change_height_cs)))
        num_filtered = before - len(items)
        if num_filtered > 0:
            self.log.info(f"Filtered {num_filtered} spam transactions")

        async def receive_and_validate(inner_states: List[CoinState], inner_idx_start: int, cs_heights: List[uint32]):
            try:
                assert self.validation_semaphore is not None
                async with self.validation_semaphore:
                    if header_hash is not None:
                        assert height is not None
                        for inner_state in inner_states:
                            self.add_state_to_race_cache(header_hash, height, inner_state)
                            self.log.info(f"Added to race cache: {height}, {inner_state}")
                    valid_states = [
                        inner_state
                        for inner_state in inner_states
                        if await self.validate_received_state_from_peer(inner_state, peer, cache, fork_height)
                    ]
                    if len(valid_states) > 0:
                        async with self.wallet_state_manager.db_wrapper.writer():
                            self.log.info(
                                f"new coin state received ({inner_idx_start}-"
                                f"{inner_idx_start + len(inner_states) - 1}/ {len(items)})"
                            )
                            try:
                                await self.wallet_state_manager.new_coin_state(valid_states, peer, fork_height)

                                if update_finished_height:
                                    if len(cs_heights) == 1:
                                        # We have processed all past tasks, so we can increase the height safely
                                        synced_up_to = last_change_height_cs(valid_states[-1]) - 1
                                    else:
                                        # We know we have processed everything before this min height
                                        synced_up_to = min(cs_heights) - 1
                                    await self.wallet_state_manager.blockchain.set_finished_sync_up_to(synced_up_to)
                            except Exception as e:
                                tb = traceback.format_exc()
                                self.log.error(f"Exception while adding state: {e} {tb}")
                            else:
                                await self.wallet_state_manager.blockchain.clean_block_records()

            except Exception as e:
                tb = traceback.format_exc()
                if self._shut_down:
                    self.log.debug(f"Shutting down while adding state : {e} {tb}")
                else:
                    self.log.error(f"Exception while adding state: {e} {tb}")
            finally:
                cs_heights.remove(last_change_height_cs(inner_states[0]))

        idx = 1
        # Keep chunk size below 1000 just in case, windows has sqlite limits of 999 per query
        # Untrusted has a smaller batch size since validation has to happen which takes a while
        chunk_size: int = 900 if trusted else 10
        for states in chunks(items, chunk_size):
            if self._server is None:
                self.log.error("No server")
                await asyncio.gather(*all_tasks)
                return False
            if peer.peer_node_id not in self.server.all_connections:
                self.log.error(f"Disconnected from peer {peer.peer_node_id} host {peer.peer_host}")
                await asyncio.gather(*all_tasks)
                return False
            if trusted:
                async with self.wallet_state_manager.db_wrapper.writer():
                    try:
                        self.log.info(f"new coin state received ({idx}-" f"{idx + len(states) - 1}/ {len(items)})")
                        await self.wallet_state_manager.new_coin_state(states, peer, fork_height)
                        if update_finished_height:
                            await self.wallet_state_manager.blockchain.set_finished_sync_up_to(
                                last_change_height_cs(states[-1]) - 1
                            )
                    except Exception as e:
                        tb = traceback.format_exc()
                        self.log.error(f"Error adding states.. {e} {tb}")
                        return False
                    else:
                        await self.wallet_state_manager.blockchain.clean_block_records()

            else:
                while len(concurrent_tasks_cs_heights) >= target_concurrent_tasks:
                    await asyncio.sleep(0.1)
                    if self._shut_down:
                        self.log.info("Terminating receipt and validation due to shut down request")
                        await asyncio.gather(*all_tasks)
                        return False
                concurrent_tasks_cs_heights.append(last_change_height_cs(states[0]))
                all_tasks.append(asyncio.create_task(receive_and_validate(states, idx, concurrent_tasks_cs_heights)))
            idx += len(states)

        still_connected = self._server is not None and peer.peer_node_id in self.server.all_connections
        await asyncio.gather(*all_tasks)
        await self.update_ui()
        return still_connected and self._server is not None and peer.peer_node_id in self.server.all_connections

    async def get_coins_with_puzzle_hash(self, puzzle_hash) -> List[CoinState]:
        # TODO Use trusted peer, otherwise try untrusted
        all_nodes = self.server.get_connections(NodeType.FULL_NODE)
        if len(all_nodes) == 0:
            raise ValueError("Not connected to the full node")
        first_node = all_nodes[0]
        msg = wallet_protocol.RegisterForPhUpdates(puzzle_hash, uint32(0))
        coin_state: Optional[RespondToPhUpdates] = await first_node.register_interest_in_puzzle_hash(msg)
        # TODO validate state if received from untrusted peer
        assert coin_state is not None
        return coin_state.coin_states

    async def is_peer_synced(
        self, peer: WSChiaConnection, header_block: HeaderBlock, request_time: uint64
    ) -> Optional[uint64]:
        # Get last timestamp
        last_tx: Optional[HeaderBlock] = await fetch_last_tx_from_peer(header_block.height, peer)
        latest_timestamp: Optional[uint64] = None
        if last_tx is not None:
            assert last_tx.foliage_transaction_block is not None
            latest_timestamp = last_tx.foliage_transaction_block.timestamp

        # Return None if not synced
        if latest_timestamp is None or self.config["testing"] is False and latest_timestamp < request_time - 600:
            return None
        return latest_timestamp

    def is_trusted(self, peer) -> bool:
        return self.server.is_trusted_peer(peer, self.config["trusted_peers"])

    def add_state_to_race_cache(self, header_hash: bytes32, height: uint32, coin_state: CoinState) -> None:
        # Clears old state that is no longer relevant
        delete_threshold = 100
        for rc_height, rc_hh in self.race_cache_hashes:
            if height - delete_threshold >= rc_height:
                self.race_cache.pop(rc_hh)
        self.race_cache_hashes = [
            (rc_height, rc_hh) for rc_height, rc_hh in self.race_cache_hashes if height - delete_threshold < rc_height
        ]

        if header_hash not in self.race_cache:
            self.race_cache[header_hash] = set()
        self.race_cache[header_hash].add(coin_state)

    async def state_update_received(self, request: wallet_protocol.CoinStateUpdate, peer: WSChiaConnection) -> None:
        # This gets called every time there is a new coin or puzzle hash change in the DB
        # that is of interest to this wallet. It is not guaranteed to come for every height. This message is guaranteed
        # to come before the corresponding new_peak for each height. We handle this differently for trusted and
        # untrusted peers. For trusted, we always process the state, and we process reorgs as well.
        for coin in request.items:
            self.log.info(f"request coin: {coin.coin.name().hex()}{coin}")

        async with self.wallet_state_manager.lock:
            await self.receive_state_from_peer(
                request.items,
                peer,
                request.fork_height,
                request.height,
                request.peak_hash,
            )

    def get_full_node_peer(self) -> Optional[WSChiaConnection]:
        """
        Get a full node, preferring synced & trusted > synced & untrusted > unsynced & trusted > unsynced & untrusted
        """
        full_nodes: List[WSChiaConnection] = self.get_full_node_peers_in_order()
        if len(full_nodes) == 0:
            return None
        return full_nodes[0]

    def get_full_node_peers_in_order(self) -> List[WSChiaConnection]:
        """
        Get all full nodes sorted:
         preferring synced & trusted > synced & untrusted > unsynced & trusted > unsynced & untrusted
        """
        if self._server is None:
            return []

        synced_and_trusted: List[WSChiaConnection] = []
        synced: List[WSChiaConnection] = []
        trusted: List[WSChiaConnection] = []
        neither: List[WSChiaConnection] = []
        all_nodes: List[WSChiaConnection] = self.server.get_connections(NodeType.FULL_NODE)
        random.shuffle(all_nodes)
        for node in all_nodes:
            we_synced_to_it = node.peer_node_id in self.synced_peers
            is_trusted = self.is_trusted(node)
            if we_synced_to_it and is_trusted:
                synced_and_trusted.append(node)
            elif we_synced_to_it:
                synced.append(node)
            elif is_trusted:
                trusted.append(node)
            else:
                neither.append(node)
        return synced_and_trusted + synced + trusted + neither

    async def disconnect_and_stop_wpeers(self) -> None:
        if self._server is None:
            return

        # Close connection of non-trusted peers
        full_node_connections = self.server.get_connections(NodeType.FULL_NODE)
        if len(full_node_connections) > 1:
            for peer in full_node_connections:
                if not self.is_trusted(peer):
                    await peer.close()

        if self.wallet_peers is not None:
            await self.wallet_peers.ensure_is_closed()
            self.wallet_peers = None

    async def check_for_synced_trusted_peer(self, header_block: HeaderBlock, request_time: uint64) -> bool:
        if self._server is None:
            return False
        for peer in self.server.get_connections(NodeType.FULL_NODE):
            if self.is_trusted(peer) and await self.is_peer_synced(peer, header_block, request_time):
                return True
        return False

    async def get_timestamp_for_height(self, height: uint32) -> uint64:
        """
        Returns the timestamp for transaction block at h=height, if not transaction block, backtracks until it finds
        a transaction block
        """
        if height in self.height_to_time:
            return self.height_to_time[height]

        for cache in self.untrusted_caches.values():
            cache_ts: Optional[uint64] = cache.get_height_timestamp(height)
            if cache_ts is not None:
                return cache_ts

        peers: List[WSChiaConnection] = self.get_full_node_peers_in_order()
        last_tx_block: Optional[HeaderBlock] = None
        for peer in peers:
            last_tx_block = await fetch_last_tx_from_peer(height, peer)
            if last_tx_block is None:
                continue

            assert last_tx_block.foliage_transaction_block is not None
            self.get_cache_for_peer(peer).add_to_blocks(last_tx_block)
            return last_tx_block.foliage_transaction_block.timestamp

        raise PeerRequestException("Error fetching timestamp from all peers")

    async def new_peak_wallet(self, new_peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection):
        if self._wallet_state_manager is None:
            # When logging out of wallet
            self.log.debug("state manager is None (shutdown)")
            return
        request_time = uint64(int(time.time()))
        trusted: bool = self.is_trusted(peer)
        peak_hb: Optional[HeaderBlock] = await self.wallet_state_manager.blockchain.get_peak_block()
        if peak_hb is not None and new_peak.weight < peak_hb.weight:
            # Discards old blocks, but accepts blocks that are equal in weight to peak
            self.log.debug("skip block with lower weight.")
            return

        request = wallet_protocol.RequestBlockHeader(new_peak.height)
        response: Optional[RespondBlockHeader] = await peer.request_block_header(request)
        if response is None:
            self.log.warning(f"Peer {peer.get_peer_info()} did not respond in time.")
            await peer.close(120)
            return

        new_peak_hb: HeaderBlock = response.header_block
        # check response is what we asked for
        if (
            new_peak_hb.header_hash != new_peak.header_hash
            or new_peak_hb.weight != new_peak.weight
            or new_peak_hb.height != new_peak.height
        ):
            self.log.warning(f"bad header block response from Peer {peer.get_peer_info()}.")
            # todo maybe accept the block if
            #  new_peak_hb.height == new_peak.height and new_peak_hb.weight >= new_peak.weight

            # dont disconnect from peer, this might be a reorg
            return

        latest_timestamp: Optional[uint64] = await self.is_peer_synced(peer, new_peak_hb, request_time)
        if latest_timestamp is None:
            if trusted:
                self.log.debug(f"Trusted peer {peer.get_peer_info()} is not synced.")
            else:
                self.log.warning(f"Non-trusted peer {peer.get_peer_info()} is not synced, disconnecting")
                await peer.close(120)
            return

        if self.is_trusted(peer):
            await self.new_peak_from_trusted(new_peak_hb, latest_timestamp, peer)
        else:
            if not await self.new_peak_from_untrusted(new_peak_hb, peer, request_time):
                return

        if peer.peer_node_id in self.synced_peers:
            await self.wallet_state_manager.blockchain.set_finished_sync_up_to(new_peak.height)
        # todo why do we call this if there was an exception / the sync is not finished
        async with self.wallet_state_manager.lock:
            await self.wallet_state_manager.new_peak(new_peak)

    async def new_peak_from_trusted(self, new_peak_hb: HeaderBlock, latest_timestamp: uint64, peer: WSChiaConnection):
        current_height: uint32 = await self.wallet_state_manager.blockchain.get_finished_sync_up_to()
        async with self.wallet_state_manager.lock:
            await self.wallet_state_manager.blockchain.set_peak_block(new_peak_hb, latest_timestamp)
            # Disconnect from all untrusted peers if our local node is trusted and synced
            await self.disconnect_and_stop_wpeers()
            # Sync to trusted node if we haven't done so yet. As long as we have synced once (and not
            # disconnected), we assume that the full node will continue to give us state updates, so we do
            # not need to resync.
            if peer.peer_node_id not in self.synced_peers:
                if new_peak_hb.height - current_height > self.LONG_SYNC_THRESHOLD:
                    self.wallet_state_manager.set_sync_mode(True)
                self._primary_peer_sync_task = asyncio.create_task(
                    self.long_sync(new_peak_hb.height, peer, uint32(max(0, current_height - 256)), rollback=True)
                )
                await self._primary_peer_sync_task
                self._primary_peer_sync_task = None
                self.wallet_state_manager.set_sync_mode(False)

    async def new_peak_from_untrusted(
        self, new_peak_hb: HeaderBlock, peer: WSChiaConnection, request_time: uint64
    ) -> bool:
        far_behind: bool = (
            new_peak_hb.height - await self.wallet_state_manager.blockchain.get_finished_sync_up_to()
            > self.LONG_SYNC_THRESHOLD
        )

        if new_peak_hb.height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
            # this is the case happens chain is shorter then WEIGHT_PROOF_RECENT_BLOCKS
            return await self.sync_from_untrusted_close_to_peak(new_peak_hb, peer)

        if not far_behind and peer.peer_node_id in self.synced_peers:
            # This is the (untrusted) case where we already synced and are not too far behind. Here we just
            # fetch one by one.
            return await self.sync_from_untrusted_close_to_peak(new_peak_hb, peer)

        # we haven't synced fully to this peer yet
        syncing = False
        if far_behind or len(self.synced_peers) == 0:
            syncing = True
            self.wallet_state_manager.set_sync_mode(True)

        secondary_sync_running = (
            self._secondary_peer_sync_task is not None and self._secondary_peer_sync_task.done() is False
        )
        if not syncing and secondary_sync_running:
            self.log.info("Will not do secondary sync, there is already another sync task running.")
            return False

        if await self.check_for_synced_trusted_peer(new_peak_hb, request_time):
            self.log.info("Cancelling untrusted sync, we are connected to a trusted peer")
            return False

        try:
            await self.long_sync_from_untrusted(syncing, new_peak_hb, peer)
        except Exception:
            self.log.exception(f"Error syncing to {peer.get_peer_info()}")
            await peer.close()
            if syncing:
                self.wallet_state_manager.set_sync_mode(False)
            return False
        return True

    async def long_sync_from_untrusted(self, syncing: bool, new_peak_hb: HeaderBlock, peer: WSChiaConnection):
        current_height: uint32 = await self.wallet_state_manager.blockchain.get_finished_sync_up_to()
        weight_proof, summaries, block_records = await self.fetch_and_validate_the_weight_proof(peer, new_peak_hb)
        old_proof = self.wallet_state_manager.blockchain.synced_weight_proof
        # In this case we will not rollback so it's OK to check some older updates as well, to ensure
        # that no recent transactions are being hidden.
        fork_point: int = 0
        if syncing:
            # This usually happens the first time we start up the wallet. We roll back slightly to be
            # safe, but we don't want to rollback too much (hence 16)
            fork_point = max(0, current_height - 16)
        if old_proof is not None:
            # If the weight proof fork point is in the past, rollback more to ensure we don't have duplicate
            # state.
            fork_point = min(fork_point, get_wp_fork_point(self.constants, old_proof, weight_proof))

        await self.wallet_state_manager.blockchain.new_valid_weight_proof(weight_proof, block_records)

        if syncing:
            async with self.wallet_state_manager.lock:
                self.log.info("Primary peer syncing")
                self._primary_peer_sync_task = asyncio.create_task(
                    self.long_sync(new_peak_hb.height, peer, fork_point, rollback=True)
                )
                await self._primary_peer_sync_task
                self._primary_peer_sync_task = None
            self.log.info(f"New peak wallet.. {new_peak_hb.height} {peer.get_peer_info()} 12")
            return

        # we exit earlier in the case where syncing is False and a Secondary sync is running
        assert self._secondary_peer_sync_task is None or self._secondary_peer_sync_task.done()
        self.log.info("Secondary peer syncing")
        self._secondary_peer_sync_task = asyncio.create_task(
            self.long_sync(new_peak_hb.height, peer, fork_point, rollback=False)
        )

    async def sync_from_untrusted_close_to_peak(self, new_peak_hb, peer) -> bool:
        async with self.wallet_state_manager.lock:
            peak_hb = await self.wallet_state_manager.blockchain.get_peak_block()
            if peak_hb is None or new_peak_hb.weight > peak_hb.weight:
                backtrack_fork_height: int = await self.wallet_short_sync_backtrack(new_peak_hb, peer)
            else:
                backtrack_fork_height = new_peak_hb.height - 1

            if peer.peer_node_id not in self.synced_peers:
                # Edge case, this happens when the peak < WEIGHT_PROOF_RECENT_BLOCKS
                # we still want to subscribe for all phs and coins.
                # (Hints are not in filter)
                all_coin_ids: List[bytes32] = await self.get_coin_ids_to_subscribe(uint32(0))
                phs: List[bytes32] = await self.get_puzzle_hashes_to_subscribe()
                ph_updates: List[CoinState] = await subscribe_to_phs(phs, peer, uint32(0))
                coin_updates: List[CoinState] = await subscribe_to_coin_updates(all_coin_ids, peer, uint32(0))
                peer_new_peak_height, peer_new_peak_hash = self.node_peaks[peer.peer_node_id]
                success = await self.receive_state_from_peer(
                    ph_updates + coin_updates,
                    peer,
                    height=peer_new_peak_height,
                    header_hash=peer_new_peak_hash,
                )
                if success:
                    self.synced_peers.add(peer.peer_node_id)
            else:
                if peak_hb is not None and new_peak_hb.weight <= peak_hb.weight:
                    # Don't process blocks at the same weight
                    return False

            # For every block, we need to apply the cache from race_cache
            for potential_height in range(backtrack_fork_height + 1, new_peak_hb.height + 1):
                header_hash = self.wallet_state_manager.blockchain.height_to_hash(uint32(potential_height))
                if header_hash in self.race_cache:
                    self.log.info(f"Receiving race state: {self.race_cache[header_hash]}")
                    await self.receive_state_from_peer(list(self.race_cache[header_hash]), peer)

            self.wallet_state_manager.state_changed("new_block")
            self.wallet_state_manager.set_sync_mode(False)
            self.log.info(f"Finished processing new peak of {new_peak_hb.height}")
            return True

    async def wallet_short_sync_backtrack(self, header_block: HeaderBlock, peer: WSChiaConnection) -> int:
        peak: Optional[HeaderBlock] = await self.wallet_state_manager.blockchain.get_peak_block()

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
        peak_height = await self.wallet_state_manager.blockchain.get_finished_sync_up_to()
        if fork_height < peak_height:
            self.log.info(f"Rolling back to {fork_height}")
            # we should clear all peers since this is a full rollback
            await self.perform_atomic_rollback(fork_height)
            await self.update_ui()

        if peak is not None:
            assert header_block.weight >= peak.weight
        for block in blocks:
            # Set blockchain to the latest peak
            res, err = await self.wallet_state_manager.blockchain.receive_block(block)
            if res == ReceiveBlockResult.INVALID_BLOCK:
                raise ValueError(err)

        return fork_height

    async def update_ui(self):
        for wallet_id, wallet in self.wallet_state_manager.wallets.items():
            self.wallet_state_manager.state_changed("coin_removed", wallet_id)
            self.wallet_state_manager.state_changed("coin_added", wallet_id)

    async def fetch_and_validate_the_weight_proof(
        self, peer: WSChiaConnection, peak: HeaderBlock
    ) -> Tuple[WeightProof, List[SubEpochSummary], List[BlockRecord]]:
        assert self._weight_proof_handler is not None
        weight_request = RequestProofOfWeight(peak.height, peak.header_hash)
        wp_timeout = self.config.get("weight_proof_timeout", 360)
        self.log.debug(f"weight proof timeout is {wp_timeout} sec")
        weight_proof_response: RespondProofOfWeight = await peer.request_proof_of_weight(
            weight_request, timeout=wp_timeout
        )

        if weight_proof_response is None:
            raise Exception("weight proof response was none")

        start_validation = time.time()
        weight_proof = weight_proof_response.wp

        if weight_proof.recent_chain_data[-1].height != peak.height:
            raise Exception("weight proof height does not match peak")
        if weight_proof.recent_chain_data[-1].weight != peak.weight:
            raise Exception("weight proof weight does not match peak")
        if weight_proof.recent_chain_data[-1].header_hash != peak.header_hash:
            raise Exception("weight proof peak hash does not match peak")

        if weight_proof.get_hash() in self.valid_wp_cache:
            valid, fork_point, summaries, block_records = self.valid_wp_cache[weight_proof.get_hash()]
        else:
            old_proof = self.wallet_state_manager.blockchain.synced_weight_proof
            fork_point = get_wp_fork_point(self.constants, old_proof, weight_proof)
            start_validation = time.time()
            (
                valid,
                summaries,
                block_records,
            ) = await self._weight_proof_handler.validate_weight_proof(weight_proof, False, old_proof)
            if not valid:
                raise Exception("weight proof failed validation")
            self.valid_wp_cache[weight_proof.get_hash()] = valid, fork_point, summaries, block_records

        end_validation = time.time()
        self.log.info(f"It took {end_validation - start_validation} time to validate the weight proof")
        return weight_proof, summaries, block_records

    async def get_puzzle_hashes_to_subscribe(self) -> List[bytes32]:
        all_puzzle_hashes = list(await self.wallet_state_manager.puzzle_store.get_all_puzzle_hashes())
        # Get all phs from interested store
        interested_puzzle_hashes = [
            t[0] for t in await self.wallet_state_manager.interested_store.get_interested_puzzle_hashes()
        ]
        all_puzzle_hashes.extend(interested_puzzle_hashes)
        return all_puzzle_hashes

    async def get_coin_ids_to_subscribe(self, min_height: int) -> List[bytes32]:
        all_coin_names: Set[bytes32] = await self.wallet_state_manager.coin_store.get_coin_names_to_check(min_height)
        removed_names = await self.wallet_state_manager.trade_manager.get_coins_of_interest()
        all_coin_names.update(set(removed_names))
        all_coin_names.update(await self.wallet_state_manager.interested_store.get_interested_coin_ids())
        return list(all_coin_names)

    async def validate_received_state_from_peer(
        self,
        coin_state: CoinState,
        peer: WSChiaConnection,
        peer_request_cache: PeerRequestCache,
        fork_height: Optional[uint32],
    ) -> bool:
        """
        Returns all state that is valid and included in the blockchain proved by the weight proof. If return_old_states
        is False, only new states that are not in the coin_store are returned.
        """
        # Only use the cache if we are talking about states before the fork point. If we are evaluating something
        # in a reorg, we cannot use the cache, since we don't know if it's actually in the new chain after the reorg.
        if await can_use_peer_request_cache(coin_state, peer_request_cache, fork_height):
            return True

        spent_height: Optional[uint32] = None if coin_state.spent_height is None else uint32(coin_state.spent_height)
        confirmed_height: Optional[uint32] = (
            None if coin_state.created_height is None else uint32(coin_state.created_height)
        )
        current = await self.wallet_state_manager.coin_store.get_coin_record(coin_state.coin.name())
        # if remote state is same as current local state we skip validation

        # CoinRecord unspent = height 0, coin state = None. We adjust for comparison below
        current_spent_height = None
        if current is not None and current.spent_block_height != 0:
            current_spent_height = current.spent_block_height

        # Same as current state, nothing to do
        if (
            current is not None
            and current_spent_height == spent_height
            and current.confirmed_block_height == confirmed_height
        ):
            peer_request_cache.add_to_states_validated(coin_state)
            return True

        reorg_mode = False

        # If coin was removed from the blockchain
        if confirmed_height is None:
            if current is None:
                # Coin does not exist in local DB, so no need to do anything
                return False
            # This coin got reorged
            reorg_mode = True
            confirmed_height = current.confirmed_block_height

        # request header block for created height
        state_block: Optional[HeaderBlock] = peer_request_cache.get_block(confirmed_height)
        if state_block is None or reorg_mode:
            state_blocks = await request_header_blocks(peer, confirmed_height, confirmed_height)
            if state_blocks is None:
                return False
            state_block = state_blocks[0]
            assert state_block is not None
            peer_request_cache.add_to_blocks(state_block)

        # get proof of inclusion
        assert state_block.foliage_transaction_block is not None
        validate_additions_result = await request_and_validate_additions(
            peer,
            peer_request_cache,
            state_block.height,
            state_block.header_hash,
            coin_state.coin.puzzle_hash,
            state_block.foliage_transaction_block.additions_root,
        )

        if validate_additions_result is False:
            self.log.warning("Validate false 1")
            await peer.close(9999)
            return False

        # If spent_height is None, we need to validate that the creation block is actually in the longest blockchain.
        # Otherwise, we don't have to, since we will validate the spent block later.
        if coin_state.spent_height is None:
            validated = await self.validate_block_inclusion(state_block, peer, peer_request_cache)
            if not validated:
                return False

        # TODO: make sure all cases are covered
        if current is not None:
            if spent_height is None and current.spent_block_height != 0:
                # Peer is telling us that coin that was previously known to be spent is not spent anymore
                # Check old state

                spent_state_blocks: Optional[List[HeaderBlock]] = await request_header_blocks(
                    peer, current.spent_block_height, current.spent_block_height
                )
                if spent_state_blocks is None:
                    return False
                spent_state_block = spent_state_blocks[0]
                assert spent_state_block.height == current.spent_block_height
                assert spent_state_block.foliage_transaction_block is not None
                peer_request_cache.add_to_blocks(spent_state_block)

                validate_removals_result: bool = await request_and_validate_removals(
                    peer,
                    current.spent_block_height,
                    spent_state_block.header_hash,
                    coin_state.coin.name(),
                    spent_state_block.foliage_transaction_block.removals_root,
                )
                if validate_removals_result is False:
                    self.log.warning("Validate false 2")
                    await peer.close(9999)
                    return False
                validated = await self.validate_block_inclusion(spent_state_block, peer, peer_request_cache)
                if not validated:
                    return False

        if spent_height is not None:
            # request header block for created height
            cached_spent_state_block = peer_request_cache.get_block(spent_height)
            if cached_spent_state_block is None:
                spent_state_blocks = await request_header_blocks(peer, spent_height, spent_height)
                if spent_state_blocks is None:
                    return False
                spent_state_block = spent_state_blocks[0]
                assert spent_state_block.height == spent_height
                assert spent_state_block.foliage_transaction_block is not None
                peer_request_cache.add_to_blocks(spent_state_block)
            else:
                spent_state_block = cached_spent_state_block
            assert spent_state_block is not None
            assert spent_state_block.foliage_transaction_block is not None
            validate_removals_result = await request_and_validate_removals(
                peer,
                spent_state_block.height,
                spent_state_block.header_hash,
                coin_state.coin.name(),
                spent_state_block.foliage_transaction_block.removals_root,
            )
            if validate_removals_result is False:
                self.log.warning("Validate false 3")
                await peer.close(9999)
                return False
            validated = await self.validate_block_inclusion(spent_state_block, peer, peer_request_cache)
            if not validated:
                return False
        peer_request_cache.add_to_states_validated(coin_state)

        return True

    async def validate_block_inclusion(
        self, block: HeaderBlock, peer: WSChiaConnection, peer_request_cache: PeerRequestCache
    ) -> bool:
        if self.wallet_state_manager.blockchain.contains_height(block.height):
            stored_hash = self.wallet_state_manager.blockchain.height_to_hash(block.height)
            stored_record = self.wallet_state_manager.blockchain.try_block_record(stored_hash)
            if stored_record is not None:
                if stored_record.header_hash == block.header_hash:
                    return True

        weight_proof: Optional[WeightProof] = self.wallet_state_manager.blockchain.synced_weight_proof
        if weight_proof is None:
            return False

        if block.height >= weight_proof.recent_chain_data[0].height:
            # this was already validated as part of the wp validation
            index = block.height - weight_proof.recent_chain_data[0].height
            if index >= len(weight_proof.recent_chain_data):
                return False
            if weight_proof.recent_chain_data[index].header_hash != block.header_hash:
                self.log.error("Failed validation 1")
                return False
            return True

        # block is not included in wp recent chain
        start = block.height + 1
        compare_to_recent = False
        inserted: int = 0
        first_height_recent = weight_proof.recent_chain_data[0].height
        if start > first_height_recent - 1000:
            # compare up to weight_proof.recent_chain_data[0].height
            compare_to_recent = True
            end = first_height_recent
        else:
            # get ses from wp
            start_height = block.height
            end_height = block.height + 32
            ses_start_height = 0
            end = 0
            for idx, ses in enumerate(weight_proof.sub_epochs):
                if idx == len(weight_proof.sub_epochs) - 1:
                    break
                next_ses_height = (idx + 1) * self.constants.SUB_EPOCH_BLOCKS + weight_proof.sub_epochs[
                    idx + 1
                ].num_blocks_overflow
                # start_ses_hash
                if ses_start_height <= start_height < next_ses_height:
                    inserted = idx + 1
                    if ses_start_height < end_height < next_ses_height:
                        end = next_ses_height
                        break
                    else:
                        if idx > len(weight_proof.sub_epochs) - 3:
                            break
                        # else add extra ses as request start <-> end spans two ses
                        end = (idx + 2) * self.constants.SUB_EPOCH_BLOCKS + weight_proof.sub_epochs[
                            idx + 2
                        ].num_blocks_overflow
                        inserted += 1
                        break
                ses_start_height = next_ses_height

        if end == 0:
            self.log.error("Error finding sub epoch")
            return False
        all_peers_c = self.server.get_connections(NodeType.FULL_NODE)
        all_peers = [(con, self.is_trusted(con)) for con in all_peers_c]
        blocks: Optional[List[HeaderBlock]] = await fetch_header_blocks_in_range(
            start, end, peer_request_cache, all_peers
        )
        if blocks is None:
            if self._shut_down:
                self.log.debug(f"Shutting down, block fetching from: {start} to {end} canceled.")
            else:
                self.log.error(f"Error fetching blocks {start} {end}")
            return False

        if compare_to_recent and weight_proof.recent_chain_data[0].header_hash != blocks[-1].header_hash:
            self.log.error("Failed validation 3")
            return False

        if not compare_to_recent:
            last = blocks[-1].finished_sub_slots[-1].reward_chain.get_hash()
            if last != weight_proof.sub_epochs[inserted].reward_chain_hash:
                self.log.error("Failed validation 4")
                return False
        pk_m_sig: List[Tuple[G1Element, bytes32, G2Element]] = []
        sigs_to_cache: List[HeaderBlock] = []
        blocks_to_cache: List[Tuple[bytes32, uint32]] = []

        signatures_to_validate: int = 30
        for idx in range(len(blocks)):
            en_block = blocks[idx]
            if idx < signatures_to_validate and not peer_request_cache.in_block_signatures_validated(en_block):
                # Validate that the block is buried in the foliage by checking the signatures
                pk_m_sig.append(
                    (
                        en_block.reward_chain_block.proof_of_space.plot_public_key,
                        en_block.foliage.foliage_block_data.get_hash(),
                        en_block.foliage.foliage_block_data_signature,
                    )
                )
                sigs_to_cache.append(en_block)

            # This is the reward chain challenge. If this is in the cache, it means the prev block
            # has been validated. We must at least check the first block to ensure they are connected
            reward_chain_hash: bytes32 = en_block.reward_chain_block.reward_chain_ip_vdf.challenge
            if idx != 0 and peer_request_cache.in_blocks_validated(reward_chain_hash):
                # As soon as we see a block we have already concluded is in the chain, we can quit.
                if idx > signatures_to_validate:
                    break
            else:
                # Validate that the block is committed to by the weight proof
                if idx == 0:
                    prev_block_rc_hash: bytes32 = block.reward_chain_block.get_hash()
                    prev_hash = block.header_hash
                else:
                    prev_block_rc_hash = blocks[idx - 1].reward_chain_block.get_hash()
                    prev_hash = blocks[idx - 1].header_hash

                if not en_block.prev_header_hash == prev_hash:
                    self.log.error("Failed validation 5")
                    return False

                if len(en_block.finished_sub_slots) > 0:
                    reversed_slots = en_block.finished_sub_slots.copy()
                    reversed_slots.reverse()
                    for slot_idx, slot in enumerate(reversed_slots[:-1]):
                        hash_val = reversed_slots[slot_idx + 1].reward_chain.get_hash()
                        if not hash_val == slot.reward_chain.end_of_slot_vdf.challenge:
                            self.log.error("Failed validation 6")
                            return False
                    if not prev_block_rc_hash == reversed_slots[-1].reward_chain.end_of_slot_vdf.challenge:
                        self.log.error("Failed validation 7")
                        return False
                else:
                    if not prev_block_rc_hash == reward_chain_hash:
                        self.log.error("Failed validation 8")
                        return False
                blocks_to_cache.append((reward_chain_hash, en_block.height))

        agg_sig: G2Element = AugSchemeMPL.aggregate([sig for (_, _, sig) in pk_m_sig])
        if not AugSchemeMPL.aggregate_verify([pk for (pk, _, _) in pk_m_sig], [m for (_, m, _) in pk_m_sig], agg_sig):
            self.log.error("Failed signature validation")
            return False
        for header_block in sigs_to_cache:
            peer_request_cache.add_to_block_signatures_validated(header_block)
        for reward_chain_hash, height in blocks_to_cache:
            peer_request_cache.add_to_blocks_validated(reward_chain_hash, height)
        return True

    async def fetch_puzzle_solution(self, height: uint32, coin: Coin, peer: WSChiaConnection) -> CoinSpend:
        solution_response = await peer.request_puzzle_solution(
            wallet_protocol.RequestPuzzleSolution(coin.name(), height)
        )
        if solution_response is None or not isinstance(solution_response, wallet_protocol.RespondPuzzleSolution):
            raise PeerRequestException(f"Was not able to obtain solution {solution_response}")
        assert solution_response.response.puzzle.get_tree_hash() == coin.puzzle_hash
        assert solution_response.response.coin_name == coin.name()

        return CoinSpend(
            coin,
            solution_response.response.puzzle,
            solution_response.response.solution,
        )

    async def get_coin_state(
        self, coin_names: List[bytes32], peer: WSChiaConnection, fork_height: Optional[uint32] = None
    ) -> List[CoinState]:
        msg = wallet_protocol.RegisterForCoinUpdates(coin_names, uint32(0))
        coin_state: Optional[RespondToCoinUpdates] = await peer.register_interest_in_coin(msg)
        if coin_state is None or not isinstance(coin_state, wallet_protocol.RespondToCoinUpdates):
            raise PeerRequestException(f"Was not able to get states for {coin_names}")

        if not self.is_trusted(peer):
            valid_list = []
            for coin in coin_state.coin_states:
                valid = await self.validate_received_state_from_peer(
                    coin, peer, self.get_cache_for_peer(peer), fork_height
                )
                if valid:
                    valid_list.append(coin)
            return valid_list

        return coin_state.coin_states

    async def fetch_children(
        self, coin_name: bytes32, peer: WSChiaConnection, fork_height: Optional[uint32] = None
    ) -> List[CoinState]:

        response: Optional[wallet_protocol.RespondChildren] = await peer.request_children(
            wallet_protocol.RequestChildren(coin_name)
        )
        if response is None or not isinstance(response, wallet_protocol.RespondChildren):
            raise PeerRequestException(f"Was not able to obtain children {response}")

        if not self.is_trusted(peer):
            request_cache = self.get_cache_for_peer(peer)
            validated = []
            for state in response.coin_states:
                valid = await self.validate_received_state_from_peer(state, peer, request_cache, fork_height)
                if valid:
                    validated.append(state)
            return validated
        return response.coin_states

    # For RPC only. You should use wallet_state_manager.add_pending_transaction for normal wallet business.
    async def push_tx(self, spend_bundle):
        msg = make_msg(
            ProtocolMessageTypes.send_transaction,
            wallet_protocol.SendTransaction(spend_bundle),
        )
        full_nodes = self.server.get_connections(NodeType.FULL_NODE)
        for peer in full_nodes:
            await peer.send_message(msg)
