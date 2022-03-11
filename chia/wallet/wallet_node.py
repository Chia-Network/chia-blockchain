import asyncio
import json
import logging
import random
import time
import traceback
from asyncio import CancelledError
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Any, Iterator

from blspy import PrivateKey, AugSchemeMPL
from packaging.version import Version

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain import ReceiveBlockResult
from chia.consensus.constants import ConsensusConstants
from chia.daemon.keychain_proxy import (
    KeychainProxyConnectionFailure,
    connect_to_keychain_and_validate,
    wrap_local_keychain,
    KeychainProxy,
    KeyringIsEmpty,
)
from chia.util.chunks import chunks
from chia.protocols import wallet_protocol
from chia.protocols.full_node_protocol import RequestProofOfWeight, RespondProofOfWeight
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import (
    RespondToCoinUpdates,
    CoinState,
    RespondToPhUpdates,
    RespondBlockHeader,
    RequestSESInfo,
    RespondSESInfo,
    RequestHeaderBlocks,
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
from chia.util.default_root import STANDALONE_ROOT_PATH
from chia.util.ints import uint32, uint64
from chia.util.keychain import KeyringIsLocked, Keychain
from chia.util.path import mkdir, path_from_root
from chia.wallet.util.new_peak_queue import NewPeakQueue, NewPeakQueueTypes, NewPeakItem
from chia.wallet.util.peer_request_cache import PeerRequestCache, can_use_peer_request_cache
from chia.wallet.util.wallet_sync_utils import (
    request_and_validate_removals,
    request_and_validate_additions,
    fetch_last_tx_from_peer,
    subscribe_to_phs,
    subscribe_to_coin_updates,
    last_change_height_cs,
    fetch_header_blocks_in_range,
)
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.wallet.transaction_record import TransactionRecord
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
    wallet_peers: Optional[WalletPeers]
    race_cache: Dict[bytes32, Set[CoinState]]
    race_cache_hashes: List[Tuple[uint32, bytes32]]
    new_peak_queue: NewPeakQueue
    _process_new_subscriptions_task: Optional[asyncio.Task]
    _secondary_peer_sync_task: Optional[asyncio.Task]
    node_peaks: Dict[bytes32, Tuple[uint32, bytes32]]
    validation_semaphore: Optional[asyncio.Semaphore]
    local_node_synced: bool

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
        self.synced_peers: Set[bytes32] = set()  # Peers that we have long synced to
        self.wallet_peers = None
        self.wallet_peers_initialized = False
        self.valid_wp_cache: Dict[bytes32, Any] = {}
        self.untrusted_caches: Dict[bytes32, PeerRequestCache] = {}
        self.race_cache = {}  # in Untrusted mode wallet might get the state update before receiving the block
        self.race_cache_hashes = []
        self._process_new_subscriptions_task = None
        self._secondary_peer_sync_task = None
        self.node_peaks = {}
        self.validation_semaphore = None
        self.local_node_synced = False
        self.LONG_SYNC_THRESHOLD = 200

    async def ensure_keychain_proxy(self) -> KeychainProxy:
        if not self.keychain_proxy:
            if self.local_keychain:
                self.keychain_proxy = wrap_local_keychain(self.local_keychain, log=self.log)
            else:
                self.keychain_proxy = await connect_to_keychain_and_validate(self.root_path, self.log)
                if not self.keychain_proxy:
                    raise KeychainProxyConnectionFailure("Failed to connect to keychain service")
        return self.keychain_proxy

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
        # Makes sure the coin_state_updates get higher priority than new_peak messages
        self.new_peak_queue = NewPeakQueue(asyncio.PriorityQueue())

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
        path = path_from_root(self.root_path, db_path_replaced.replace("v1", "v2"))
        mkdir(path.parent)

        standalone_path = path_from_root(STANDALONE_ROOT_PATH, f"{db_path_replaced.replace('v2', 'v1')}_new")
        if not path.exists():
            if standalone_path.exists():
                self.log.info(f"Copying wallet db from {standalone_path} to {path}")
                path.write_bytes(standalone_path.read_bytes())

        assert self.server is not None
        self.wallet_state_manager = await WalletStateManager.create(
            private_key,
            self.config,
            path,
            self.constants,
            self.server,
            self.root_path,
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
        self._process_new_subscriptions_task = asyncio.create_task(self._process_new_subscriptions())

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

    def _close(self):
        self.log.info("self._close")
        self.logged_in_fingerprint = None
        self._shut_down = True

        if self._process_new_subscriptions_task is not None:
            self._process_new_subscriptions_task.cancel()
        if self._secondary_peer_sync_task is not None:
            self._secondary_peer_sync_task.cancel()

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
                self.log.debug(f"sending: {msg}")
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

    async def _process_new_subscriptions(self):
        while not self._shut_down:
            # Here we process four types of messages in the queue, where the first one has higher priority (lower
            # number in the queue), and priority decreases for each type.
            peer: Optional[WSChiaConnection] = None
            item: Optional[NewPeakItem] = None
            try:
                peer, item = None, None
                item = await self.new_peak_queue.get()
                self.log.debug(f"Pulled from queue: {item}")
                assert item is not None
                if item.item_type == NewPeakQueueTypes.COIN_ID_SUBSCRIPTION:
                    # Subscriptions are the highest priority, because we don't want to process any more peaks or
                    # state updates until we are sure that we subscribed to everything that we need to. Otherwise,
                    # we might not be able to process some state.
                    coin_ids: List[bytes32] = item.data
                    for peer in self.server.get_full_node_connections():
                        coin_states: List[CoinState] = await subscribe_to_coin_updates(coin_ids, peer, uint32(0))
                        if len(coin_states) > 0:
                            async with self.wallet_state_manager.lock:
                                await self.receive_state_from_peer(coin_states, peer)
                elif item.item_type == NewPeakQueueTypes.PUZZLE_HASH_SUBSCRIPTION:
                    puzzle_hashes: List[bytes32] = item.data
                    for peer in self.server.get_full_node_connections():
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
            except CancelledError:
                self.log.info("Queue task cancelled, exiting.")
                raise
            except Exception as e:
                self.log.error(f"Exception handling {item}, {e} {traceback.format_exc()}")
                if peer is not None:
                    await peer.close(9999)

    def set_server(self, server: ChiaServer):
        self.server = server
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
        if self.wallet_state_manager is None:
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
        assert self.wallet_state_manager is not None
        start_time = time.time()

        if rollback:
            await self.wallet_state_manager.reorg_rollback(fork_height)
            self.rollback_request_caches(fork_height)
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

        if self.wallet_state_manager is None:
            return False
        trusted = self.is_trusted(peer)
        # Validate states in parallel, apply serial
        # TODO: optimize fetching
        if self.validation_semaphore is None:
            self.validation_semaphore = asyncio.Semaphore(6)

        # If there is a fork, we need to ensure that we roll back in trusted mode to properly handle reorgs
        if trusted and fork_height is not None and height is not None and fork_height != height - 1:
            await self.wallet_state_manager.reorg_rollback(fork_height)
            await self.wallet_state_manager.blockchain.set_finished_sync_up_to(fork_height)
        cache: PeerRequestCache = self.get_cache_for_peer(peer)
        if fork_height is not None:
            cache.clear_after_height(fork_height)
            self.log.info(f"Rolling back to {fork_height}")

        all_tasks: List[asyncio.Task] = []
        target_concurrent_tasks: int = 20
        concurrent_tasks_cs_heights: List[uint32] = []

        # Ensure the list is sorted
        items = sorted(items_input, key=last_change_height_cs)

        async def receive_and_validate(inner_states: List[CoinState], inner_idx_start: int, cs_heights: List[uint32]):
            assert self.wallet_state_manager is not None
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
                        async with self.wallet_state_manager.db_wrapper.lock:
                            self.log.info(
                                f"new coin state received ({inner_idx_start}-"
                                f"{inner_idx_start + len(inner_states) - 1}/ {len(items)})"
                            )
                            if self.wallet_state_manager is None:
                                return
                            try:
                                await self.wallet_state_manager.db_wrapper.commit_transaction()
                                await self.wallet_state_manager.db_wrapper.begin_transaction()
                                await self.wallet_state_manager.new_coin_state(valid_states, peer, fork_height)

                                if update_finished_height:
                                    if len(cs_heights) == 1:
                                        # We have processed all past tasks, so we can increase the height safely
                                        synced_up_to = last_change_height_cs(valid_states[-1]) - 1
                                    else:
                                        # We know we have processed everything before this min height
                                        synced_up_to = min(cs_heights) - 1
                                    await self.wallet_state_manager.blockchain.set_finished_sync_up_to(
                                        synced_up_to, in_transaction=True
                                    )
                                await self.wallet_state_manager.db_wrapper.commit_transaction()

                            except Exception as e:
                                tb = traceback.format_exc()
                                self.log.error(f"Exception while adding state: {e} {tb}")
                                await self.wallet_state_manager.db_wrapper.rollback_transaction()
                                await self.wallet_state_manager.coin_store.rebuild_wallet_cache()
                                await self.wallet_state_manager.tx_store.rebuild_tx_cache()
                                await self.wallet_state_manager.pool_store.rebuild_cache()
            except Exception as e:
                tb = traceback.format_exc()
                self.log.error(f"Exception while adding state: {e} {tb}")
            finally:
                cs_heights.remove(last_change_height_cs(inner_states[0]))

        idx = 1
        # Keep chunk size below 1000 just in case, windows has sqlite limits of 999 per query
        # Untrusted has a smaller batch size since validation has to happen which takes a while
        chunk_size: int = 900 if trusted else 10
        for states in chunks(items, chunk_size):
            if self.server is None:
                self.log.error("No server")
                return False
            if peer.peer_node_id not in self.server.all_connections:
                self.log.error(f"Disconnected from peer {peer.peer_node_id} host {peer.peer_host}")
                return False
            if trusted:
                async with self.wallet_state_manager.db_wrapper.lock:
                    try:
                        self.log.info(f"new coin state received ({idx}-" f"{idx + len(states) - 1}/ {len(items)})")
                        await self.wallet_state_manager.db_wrapper.commit_transaction()
                        await self.wallet_state_manager.db_wrapper.begin_transaction()
                        await self.wallet_state_manager.new_coin_state(states, peer, fork_height)
                        await self.wallet_state_manager.db_wrapper.commit_transaction()
                        await self.wallet_state_manager.blockchain.set_finished_sync_up_to(
                            last_change_height_cs(states[-1]) - 1, in_transaction=True
                        )
                    except Exception as e:
                        await self.wallet_state_manager.db_wrapper.rollback_transaction()
                        await self.wallet_state_manager.coin_store.rebuild_wallet_cache()
                        await self.wallet_state_manager.tx_store.rebuild_tx_cache()
                        await self.wallet_state_manager.pool_store.rebuild_cache()
                        tb = traceback.format_exc()
                        self.log.error(f"Error adding states.. {e} {tb}")
                        return False
            else:
                while len(concurrent_tasks_cs_heights) >= target_concurrent_tasks:
                    await asyncio.sleep(0.1)
                    if self._shut_down:
                        self.log.info("Terminating receipt and validation due to shut down request")
                        return False
                concurrent_tasks_cs_heights.append(last_change_height_cs(states[0]))
                all_tasks.append(asyncio.create_task(receive_and_validate(states, idx, concurrent_tasks_cs_heights)))
            idx += len(states)

        still_connected = self.server is not None and peer.peer_node_id in self.server.all_connections
        await asyncio.gather(*all_tasks)
        await self.update_ui()
        return still_connected and self.server is not None and peer.peer_node_id in self.server.all_connections

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
        assert self.server is not None
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
        assert self.wallet_state_manager is not None
        assert self.server is not None

        async with self.wallet_state_manager.lock:
            await self.receive_state_from_peer(
                request.items,
                peer,
                request.fork_height,
                request.height,
                request.peak_hash,
            )

    def get_full_node_peer(self) -> Optional[WSChiaConnection]:
        if self.server is None:
            return None

        nodes = self.server.get_full_node_connections()
        if len(nodes) > 0:
            return random.choice(nodes)
        else:
            return None

    async def disconnect_and_stop_wpeers(self) -> None:
        if self.server is None:
            return

        # Close connection of non-trusted peers
        if len(self.server.get_full_node_connections()) > 1:
            for peer in self.server.get_full_node_connections():
                if not self.is_trusted(peer):
                    await peer.close()

        if self.wallet_peers is not None:
            await self.wallet_peers.ensure_is_closed()
            self.wallet_peers = None

    async def check_for_synced_trusted_peer(self, header_block: HeaderBlock, request_time: uint64) -> bool:
        if self.server is None:
            return False
        for peer in self.server.get_full_node_connections():
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

        peer: Optional[WSChiaConnection] = self.get_full_node_peer()
        if peer is None:
            raise ValueError("Cannot fetch timestamp, no peers")
        self.log.debug(f"Fetching block at height: {height}")
        last_tx_block: Optional[HeaderBlock] = await fetch_last_tx_from_peer(height, peer)
        if last_tx_block is None:
            raise ValueError(f"Error fetching blocks from peer {peer.get_peer_info()}")
        assert last_tx_block.foliage_transaction_block is not None
        self.get_cache_for_peer(peer).add_to_blocks(last_tx_block)
        return last_tx_block.foliage_transaction_block.timestamp

    async def new_peak_wallet(self, new_peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection):
        if self.wallet_state_manager is None:
            # When logging out of wallet
            return
        assert self.server is not None
        request_time = uint64(int(time.time()))
        trusted: bool = self.is_trusted(peer)
        peak_hb: Optional[HeaderBlock] = await self.wallet_state_manager.blockchain.get_peak_block()
        if peak_hb is not None and new_peak.weight < peak_hb.weight:
            # Discards old blocks, but accepts blocks that are equal in weight to peak
            return

        request = wallet_protocol.RequestBlockHeader(new_peak.height)
        response: Optional[RespondBlockHeader] = await peer.request_block_header(request)
        if response is None:
            self.log.warning(f"Peer {peer.get_peer_info()} did not respond in time.")
            await peer.close(120)
            return
        header_block: HeaderBlock = response.header_block

        latest_timestamp: Optional[uint64] = await self.is_peer_synced(peer, header_block, request_time)
        if latest_timestamp is None:
            if trusted:
                self.log.debug(f"Trusted peer {peer.get_peer_info()} is not synced.")
                return
            else:
                self.log.warning(f"Non-trusted peer {peer.get_peer_info()} is not synced, disconnecting")
                await peer.close(120)
                return

        current_height: uint32 = await self.wallet_state_manager.blockchain.get_finished_sync_up_to()
        if self.is_trusted(peer):
            async with self.wallet_state_manager.lock:
                await self.wallet_state_manager.blockchain.set_peak_block(header_block, latest_timestamp)
                # Disconnect from all untrusted peers if our local node is trusted and synced
                await self.disconnect_and_stop_wpeers()

                # Sync to trusted node if we haven't done so yet. As long as we have synced once (and not
                # disconnected), we assume that the full node will continue to give us state updates, so we do
                # not need to resync.
                if peer.peer_node_id not in self.synced_peers:
                    if new_peak.height - current_height > self.LONG_SYNC_THRESHOLD:
                        self.wallet_state_manager.set_sync_mode(True)
                    await self.long_sync(new_peak.height, peer, uint32(max(0, current_height - 256)), rollback=True)
                    self.wallet_state_manager.set_sync_mode(False)

        else:
            far_behind: bool = (
                new_peak.height - self.wallet_state_manager.blockchain.get_peak_height() > self.LONG_SYNC_THRESHOLD
            )

            # check if claimed peak is heavier or same as our current peak
            # if we haven't synced fully to this peer sync again
            if (
                peer.peer_node_id not in self.synced_peers or far_behind
            ) and new_peak.height >= self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
                if await self.check_for_synced_trusted_peer(header_block, request_time):
                    self.wallet_state_manager.set_sync_mode(False)
                    self.log.info("Cancelling untrusted sync, we are connected to a trusted peer")
                    return

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

                    if await self.check_for_synced_trusted_peer(header_block, request_time):
                        self.wallet_state_manager.set_sync_mode(False)
                        self.log.info("Cancelling untrusted sync, we are connected to a trusted peer")
                        return
                    assert weight_proof is not None
                    old_proof = self.wallet_state_manager.blockchain.synced_weight_proof
                    if syncing:
                        # This usually happens the first time we start up the wallet. We roll back slightly to be
                        # safe, but we don't want to rollback too much (hence 16)
                        fork_point: int = max(0, current_height - 16)
                    else:
                        # In this case we will not rollback so it's OK to check some older updates as well, to ensure
                        # that no recent transactions are being hidden.
                        fork_point = 0
                    if old_proof is not None:
                        # If the weight proof fork point is in the past, rollback more to ensure we don't have duplicate
                        # state.
                        wp_fork_point = self.wallet_state_manager.weight_proof_handler.get_fork_point(
                            old_proof, weight_proof
                        )
                        fork_point = min(fork_point, wp_fork_point)

                    await self.wallet_state_manager.blockchain.new_weight_proof(weight_proof, block_records)
                    if syncing:
                        async with self.wallet_state_manager.lock:
                            self.log.info("Primary peer syncing")
                            await self.long_sync(new_peak.height, peer, fork_point, rollback=True)
                    else:
                        if self._secondary_peer_sync_task is None or self._secondary_peer_sync_task.done():
                            self.log.info("Secondary peer syncing")
                            self._secondary_peer_sync_task = asyncio.create_task(
                                self.long_sync(new_peak.height, peer, fork_point, rollback=False)
                            )
                            return
                        else:
                            self.log.info("Will not do secondary sync, there is already another sync task running.")
                            return
                    self.log.info(f"New peak wallet.. {new_peak.height} {peer.get_peer_info()} 12")
                    if (
                        self.wallet_state_manager.blockchain.synced_weight_proof is None
                        or weight_proof.recent_chain_data[-1].weight
                        > self.wallet_state_manager.blockchain.synced_weight_proof.recent_chain_data[-1].weight
                    ):
                        await self.wallet_state_manager.blockchain.new_weight_proof(weight_proof, block_records)
                except Exception as e:
                    tb = traceback.format_exc()
                    self.log.error(f"Error syncing to {peer.get_peer_info()} {e} {tb}")
                    if syncing:
                        self.wallet_state_manager.set_sync_mode(False)
                    tb = traceback.format_exc()
                    self.log.error(f"Error syncing to {peer.get_peer_info()} {tb}")
                    await peer.close()
                    return
                if syncing:
                    self.wallet_state_manager.set_sync_mode(False)

            else:
                # This is the (untrusted) case where we already synced and are not too far behind. Here we just
                # fetch one by one.
                async with self.wallet_state_manager.lock:
                    peak_hb = await self.wallet_state_manager.blockchain.get_peak_block()
                    if peak_hb is None or new_peak.weight > peak_hb.weight:
                        backtrack_fork_height: int = await self.wallet_short_sync_backtrack(header_block, peer)
                    else:
                        backtrack_fork_height = new_peak.height - 1

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
                        if peak_hb is not None and new_peak.weight <= peak_hb.weight:
                            # Don't process blocks at the same weight
                            return

                    # For every block, we need to apply the cache from race_cache
                    for potential_height in range(backtrack_fork_height + 1, new_peak.height + 1):
                        header_hash = self.wallet_state_manager.blockchain.height_to_hash(uint32(potential_height))
                        if header_hash in self.race_cache:
                            self.log.info(f"Receiving race state: {self.race_cache[header_hash]}")
                            await self.receive_state_from_peer(list(self.race_cache[header_hash]), peer)

                    self.wallet_state_manager.state_changed("new_block")
                    self.wallet_state_manager.set_sync_mode(False)
                    self.log.info(f"Finished processing new peak of {new_peak.height}")

        if peer.peer_node_id in self.synced_peers:
            await self.wallet_state_manager.blockchain.set_finished_sync_up_to(new_peak.height)
        await self.wallet_state_manager.new_peak(new_peak)

    async def wallet_short_sync_backtrack(self, header_block: HeaderBlock, peer: WSChiaConnection) -> int:
        assert self.wallet_state_manager is not None
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
        peak_height = self.wallet_state_manager.blockchain.get_peak_height()
        if fork_height < peak_height:
            self.log.info(f"Rolling back to {fork_height}")
            await self.wallet_state_manager.reorg_rollback(fork_height)
            await self.update_ui()
        self.rollback_request_caches(fork_height)

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
    ) -> Tuple[bool, Optional[WeightProof], List[SubEpochSummary], List[BlockRecord]]:
        assert self.wallet_state_manager is not None
        assert self.wallet_state_manager.weight_proof_handler is not None

        weight_request = RequestProofOfWeight(peak.height, peak.header_hash)
        wp_timeout = self.config.get("weight_proof_timeout", 360)
        self.log.debug(f"weight proof timeout is {wp_timeout} sec")
        weight_proof_response: RespondProofOfWeight = await peer.request_proof_of_weight(
            weight_request, timeout=wp_timeout
        )

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

    async def get_coin_ids_to_subscribe(self, min_height: int) -> List[bytes32]:
        assert self.wallet_state_manager is not None
        all_coins: Set[WalletCoinRecord] = await self.wallet_state_manager.coin_store.get_coins_to_check(min_height)
        all_coin_names: Set[bytes32] = {coin_record.name() for coin_record in all_coins}
        removed_dict = await self.wallet_state_manager.trade_manager.get_coins_of_interest()
        all_coin_names.update(removed_dict.keys())
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
        assert self.wallet_state_manager is not None

        # Only use the cache if we are talking about states before the fork point. If we are evaluating something
        # in a reorg, we cannot use the cache, since we don't know if it's actually in the new chain after the reorg.
        if await can_use_peer_request_cache(coin_state, peer_request_cache, fork_height):
            return True

        spent_height = coin_state.spent_height
        confirmed_height = coin_state.created_height
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
            request = RequestHeaderBlocks(confirmed_height, confirmed_height)
            res = await peer.request_header_blocks(request)
            if res is None:
                return False
            state_block = res.header_blocks[0]
            assert state_block is not None
            peer_request_cache.add_to_blocks(state_block)

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

                request = RequestHeaderBlocks(current.spent_block_height, current.spent_block_height)
                res = await peer.request_header_blocks(request)
                spent_state_block = res.header_blocks[0]
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
            spent_state_block = peer_request_cache.get_block(spent_height)
            if spent_state_block is None:
                request = RequestHeaderBlocks(spent_height, spent_height)
                res = await peer.request_header_blocks(request)
                spent_state_block = res.header_blocks[0]
                assert spent_state_block.height == spent_height
                assert spent_state_block.foliage_transaction_block is not None
                peer_request_cache.add_to_blocks(spent_state_block)
            assert spent_state_block is not None
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
        assert self.wallet_state_manager is not None
        assert self.server is not None
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
                if block.height < self.constants.SUB_EPOCH_BLOCKS:
                    inserted = weight_proof.sub_epochs[1]
                    end = self.constants.SUB_EPOCH_BLOCKS + inserted.num_blocks_overflow
                else:
                    request = RequestSESInfo(block.height, block.height + 32)
                    res_ses: Optional[RespondSESInfo] = peer_request_cache.get_ses_request(block.height)
                    if res_ses is None:
                        res_ses = await peer.request_ses_hashes(request)
                        peer_request_cache.add_to_ses_requests(block.height, res_ses)
                    assert res_ses is not None

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

            all_peers = self.server.get_full_node_connections()
            blocks: Optional[List[HeaderBlock]] = await fetch_header_blocks_in_range(
                start, end, peer_request_cache, all_peers
            )
            if blocks is None:
                self.log.error(f"Error fetching blocks {start} {end}")
                return False

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

    async def fetch_puzzle_solution(self, peer: WSChiaConnection, height: uint32, coin: Coin) -> CoinSpend:
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

    async def get_coin_state(
        self, coin_names: List[bytes32], fork_height: Optional[uint32] = None, peer: Optional[WSChiaConnection] = None
    ) -> List[CoinState]:
        assert self.server is not None
        all_nodes = self.server.connection_by_type[NodeType.FULL_NODE]
        if len(all_nodes.keys()) == 0:
            raise ValueError("Not connected to the full node")
        # Use supplied if provided, prioritize trusted otherwise
        if peer is None:
            for node in list(all_nodes.values()):
                if self.is_trusted(node):
                    peer = node
                    break
            if peer is None:
                peer = list(all_nodes.values())[0]

        assert peer is not None
        msg = wallet_protocol.RegisterForCoinUpdates(coin_names, uint32(0))
        coin_state: Optional[RespondToCoinUpdates] = await peer.register_interest_in_coin(msg)
        assert coin_state is not None

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
        self, peer: WSChiaConnection, coin_name: bytes32, fork_height: Optional[uint32] = None
    ) -> List[CoinState]:
        response: Optional[wallet_protocol.RespondChildren] = await peer.request_children(
            wallet_protocol.RequestChildren(coin_name)
        )
        if response is None or not isinstance(response, wallet_protocol.RespondChildren):
            raise ValueError(f"Was not able to obtain children {response}")

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
        full_nodes = self.server.get_full_node_connections()
        for peer in full_nodes:
            await peer.send_message(msg)
