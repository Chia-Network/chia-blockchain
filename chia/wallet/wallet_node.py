from __future__ import annotations

import asyncio
import dataclasses
import logging
import multiprocessing
import random
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import aiosqlite
from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey
from packaging.version import Version

from chia.consensus.blockchain import AddBlockResult
from chia.consensus.constants import ConsensusConstants
from chia.daemon.keychain_proxy import KeychainProxy, connect_to_keychain_and_validate, wrap_local_keychain
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.full_node_protocol import RequestProofOfWeight, RespondProofOfWeight
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import (
    CoinState,
    CoinStateUpdate,
    NewPeakWallet,
    RegisterForCoinUpdates,
    RequestBlockHeader,
    RequestChildren,
    RespondBlockHeader,
    RespondChildren,
    RespondToCoinUpdates,
    SendTransaction,
)
from chia.rpc.rpc_server import StateChangedProtocol, default_get_connections
from chia.server.node_discovery import WalletPeers
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.peer_store_resolver import PeerStoreResolver
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.types.weight_proof import WeightProof
from chia.util.config import (
    WALLET_PEERS_PATH_KEY_DEPRECATED,
    lock_and_load_config,
    process_config_start_method,
    save_config,
)
from chia.util.db_wrapper import manage_connection
from chia.util.errors import KeychainIsEmpty, KeychainIsLocked, KeychainKeyNotFound, KeychainProxyConnectionFailure
from chia.util.ints import uint16, uint32, uint64, uint128
from chia.util.keychain import Keychain
from chia.util.misc import to_batches
from chia.util.path import path_from_root
from chia.util.profiler import mem_profile_task, profile_task
from chia.util.streamable import Streamable, streamable
from chia.wallet.puzzles.clawback.metadata import AutoClaimSettings
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.new_peak_queue import NewPeakItem, NewPeakQueue, NewPeakQueueTypes
from chia.wallet.util.peer_request_cache import PeerRequestCache, can_use_peer_request_cache
from chia.wallet.util.wallet_sync_utils import (
    PeerRequestException,
    fetch_header_blocks_in_range,
    fetch_last_tx_from_peer,
    request_and_validate_additions,
    request_and_validate_removals,
    request_header_blocks,
    sort_coin_states,
    subscribe_to_coin_updates,
    subscribe_to_phs,
)
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.wallet.wallet_weight_proof_handler import WalletWeightProofHandler, get_wp_fork_point


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


@streamable
@dataclasses.dataclass(frozen=True)
class Balance(Streamable):
    confirmed_wallet_balance: uint128 = uint128(0)
    unconfirmed_wallet_balance: uint128 = uint128(0)
    spendable_balance: uint128 = uint128(0)
    pending_change: uint64 = uint64(0)
    max_send_amount: uint128 = uint128(0)
    unspent_coin_count: uint32 = uint32(0)
    pending_coin_removal_count: uint32 = uint32(0)


@dataclasses.dataclass(frozen=True)
class PeerPeak:
    height: uint32
    hash: bytes32


@dataclasses.dataclass
class WalletNode:
    config: Dict[str, Any]
    root_path: Path
    constants: ConsensusConstants
    local_keychain: Optional[Keychain] = None

    log: logging.Logger = logging.getLogger(__name__)

    # Sync data
    state_changed_callback: Optional[StateChangedProtocol] = None
    _wallet_state_manager: Optional[WalletStateManager] = None
    _weight_proof_handler: Optional[WalletWeightProofHandler] = None
    _server: Optional[ChiaServer] = None
    sync_task: Optional[asyncio.Task[None]] = None
    logged_in_fingerprint: Optional[int] = None
    logged_in: bool = False
    _keychain_proxy: Optional[KeychainProxy] = None
    _balance_cache: Dict[int, Balance] = dataclasses.field(default_factory=dict)
    # Peers that we have long synced to
    synced_peers: Set[bytes32] = dataclasses.field(default_factory=set)
    wallet_peers: Optional[WalletPeers] = None
    peer_caches: Dict[bytes32, PeerRequestCache] = dataclasses.field(default_factory=dict)
    # in Untrusted mode wallet might get the state update before receiving the block
    race_cache: Dict[bytes32, Set[CoinState]] = dataclasses.field(default_factory=dict)
    race_cache_hashes: List[Tuple[uint32, bytes32]] = dataclasses.field(default_factory=list)
    node_peaks: Dict[bytes32, PeerPeak] = dataclasses.field(default_factory=dict)
    validation_semaphore: Optional[asyncio.Semaphore] = None
    local_node_synced: bool = False
    LONG_SYNC_THRESHOLD: int = 300
    last_wallet_tx_resend_time: int = 0
    # Duration in seconds
    coin_state_retry_seconds: int = 10
    wallet_tx_resend_timeout_secs: int = 1800
    _new_peak_queue: Optional[NewPeakQueue] = None

    _shut_down: bool = False
    _process_new_subscriptions_task: Optional[asyncio.Task[None]] = None
    _retry_failed_states_task: Optional[asyncio.Task[None]] = None
    _secondary_peer_sync_task: Optional[asyncio.Task[None]] = None

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

    def get_cache_for_peer(self, peer: WSChiaConnection) -> PeerRequestCache:
        if peer.peer_node_id not in self.peer_caches:
            self.peer_caches[peer.peer_node_id] = PeerRequestCache()
        return self.peer_caches[peer.peer_node_id]

    def rollback_request_caches(self, reorg_height: int) -> None:
        # Everything after reorg_height should be removed from the cache
        for cache in self.peer_caches.values():
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

    def set_resync_on_startup(self, fingerprint: int, enabled: bool = True) -> None:
        with lock_and_load_config(self.root_path, "config.yaml") as config:
            if enabled is True:
                config["wallet"]["reset_sync_for_fingerprint"] = fingerprint
                self.log.info("Enabled resync for wallet fingerprint: %s", fingerprint)
            else:
                self.log.debug(
                    "Trying to disable resync: %s [%s]", fingerprint, config["wallet"].get("reset_sync_for_fingerprint")
                )
                if config["wallet"].get("reset_sync_for_fingerprint") == fingerprint:
                    del config["wallet"]["reset_sync_for_fingerprint"]
                    self.log.info("Disabled resync for wallet fingerprint: %s", fingerprint)
            save_config(self.root_path, "config.yaml", config)

    def set_auto_claim(self, auto_claim_config: AutoClaimSettings) -> Dict[str, Any]:
        if auto_claim_config.batch_size < 1:
            auto_claim_config = dataclasses.replace(auto_claim_config, batch_size=uint16(50))
        auto_claim_config_json = auto_claim_config.to_json_dict()
        if "auto_claim" not in self.config or self.config["auto_claim"] != auto_claim_config_json:
            # Update in memory config
            self.config["auto_claim"] = auto_claim_config_json
            # Update config file
            with lock_and_load_config(self.root_path, "config.yaml") as config:
                config["wallet"]["auto_claim"] = self.config["auto_claim"]
                save_config(self.root_path, "config.yaml", config)
        return auto_claim_config.to_json_dict()

    async def reset_sync_db(self, db_path: Union[Path, str], fingerprint: int) -> bool:
        conn: aiosqlite.Connection
        # are not part of core wallet tables, but might appear later
        ignore_tables = {"lineage_proofs_", "sqlite_"}
        required_tables = [
            "coin_record",
            "transaction_record",
            "derivation_paths",
            "users_wallets",
            "users_nfts",
            "action_queue",
            "all_notification_ids",
            "key_val_store",
            "trade_records",
            "pool_state_transitions",
            "singleton_records",
            "mirrors",
            "launchers",
            "interested_coins",
            "interested_puzzle_hashes",
            "unacknowledged_asset_tokens",
            "coin_of_interest_to_trade_record",
            "notifications",
            "retry_store",
            "unacknowledged_asset_token_states",
            "vc_records",
            "vc_proofs",
        ]

        async with manage_connection(db_path) as conn:
            self.log.info("Resetting wallet sync data...")
            rows = list(await conn.execute_fetchall("SELECT name FROM sqlite_master WHERE type='table'"))
            names = set([x[0] for x in rows])
            names = names - set(required_tables)
            for name in names:
                for ignore_name in ignore_tables:
                    if name.startswith(ignore_name):
                        break
                else:
                    self.log.error(
                        f"Mismatch in expected schema to reset, found unexpected table: {name}. "
                        "Please check if you've run all migration scripts."
                    )
                    return False

            await conn.execute("BEGIN")
            commit = True
            tables = [row[0] for row in rows]
            try:
                if "coin_record" in tables:
                    await conn.execute("DELETE FROM coin_record")
                if "interested_coins" in tables:
                    await conn.execute("DELETE FROM interested_coins")
                if "interested_puzzle_hashes" in tables:
                    await conn.execute("DELETE FROM interested_puzzle_hashes")
                if "key_val_store" in tables:
                    await conn.execute("DELETE FROM key_val_store")
                if "users_nfts" in tables:
                    await conn.execute("DELETE FROM users_nfts")
            except aiosqlite.Error:
                self.log.exception("Error resetting sync tables")
                commit = False
            finally:
                try:
                    if commit:
                        self.log.info("Reset wallet sync data completed.")
                        await conn.execute("COMMIT")
                    else:
                        self.log.info("Reverting reset resync changes")
                        await conn.execute("ROLLBACK")
                except aiosqlite.Error:
                    self.log.exception("Error finishing reset resync db")
                # disable the resync in any case
                self.set_resync_on_startup(fingerprint, False)
            return commit

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
        if not fingerprint:
            fingerprint = self.get_last_used_fingerprint()
        multiprocessing_start_method = process_config_start_method(config=self.config, log=self.log)
        multiprocessing_context = multiprocessing.get_context(method=multiprocessing_start_method)
        self._weight_proof_handler = WalletWeightProofHandler(self.constants, multiprocessing_context)
        self.synced_peers = set()
        private_key = await self.get_private_key(fingerprint)
        if private_key is None:
            self.log_out()
            return False
        # override with private key fetched in case it's different from what was passed
        if fingerprint is None:
            fingerprint = private_key.get_g1().get_fingerprint()
        if self.config.get("enable_profiler", False):
            if sys.getprofile() is not None:
                self.log.warning("not enabling profiler, getprofile() is already set")
            else:
                asyncio.create_task(profile_task(self.root_path, "wallet", self.log))

        if self.config.get("enable_memory_profiler", False):
            asyncio.create_task(mem_profile_task(self.root_path, "wallet", self.log))

        path: Path = get_wallet_db_path(self.root_path, self.config, str(fingerprint))
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.config.get("reset_sync_for_fingerprint") == fingerprint:
            await self.reset_sync_db(path, fingerprint)

        self._wallet_state_manager = await WalletStateManager.create(
            private_key,
            self.config,
            path,
            self.constants,
            self.server,
            self.root_path,
            self,
        )

        if self.state_changed_callback is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)

        self.last_wallet_tx_resend_time = int(time.time())
        self.wallet_tx_resend_timeout_secs = self.config.get("tx_resend_timeout_secs", 60 * 60)
        self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)
        self._shut_down = False
        self._process_new_subscriptions_task = asyncio.create_task(self._process_new_subscriptions())
        self._retry_failed_states_task = asyncio.create_task(self._retry_failed_states())

        self.sync_event = asyncio.Event()
        self.log_in(private_key)
        self.wallet_state_manager.state_changed("sync_changed")

        # Populate the balance caches for all wallets
        async with self.wallet_state_manager.lock:
            for wallet_id in self.wallet_state_manager.wallets:
                await self._update_balance_cache(wallet_id)

        async with self.wallet_state_manager.puzzle_store.lock:
            index = await self.wallet_state_manager.puzzle_store.get_last_derivation_path()
            if index is None or index < self.wallet_state_manager.initial_num_public_keys - 1:
                await self.wallet_state_manager.create_more_puzzle_hashes(from_zero=True)

        if self.wallet_peers is None:
            self.initialize_wallet_peers()

        return True

    def _close(self) -> None:
        self.log.info("self._close")
        self.log_out()
        self._shut_down = True
        if self._weight_proof_handler is not None:
            self._weight_proof_handler.cancel_weight_proof_tasks()
        if self._process_new_subscriptions_task is not None:
            self._process_new_subscriptions_task.cancel()
        if self._retry_failed_states_task is not None:
            self._retry_failed_states_task.cancel()
        if self._secondary_peer_sync_task is not None:
            self._secondary_peer_sync_task.cancel()

    async def _await_closed(self, shutting_down: bool = True) -> None:
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
        self._balance_cache = {}

    def _set_state_changed_callback(self, callback: StateChangedProtocol) -> None:
        self.state_changed_callback = callback

        if self._wallet_state_manager is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)
            self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)

    def _pending_tx_handler(self) -> None:
        if self._wallet_state_manager is None:
            return None
        asyncio.create_task(self._resend_queue())

    async def _resend_queue(self) -> None:
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
            msg = make_msg(ProtocolMessageTypes.send_transaction, SendTransaction(record.spend_bundle))
            already_sent = set()
            for peer, status, _ in record.sent_to:
                if status == MempoolInclusionStatus.SUCCESS.value:
                    already_sent.add(bytes32.from_hexstr(peer))
            messages.append((msg, already_sent))

        return messages

    async def _retry_failed_states(self) -> None:
        while not self._shut_down:
            try:
                await asyncio.sleep(self.coin_state_retry_seconds)
                if self.wallet_state_manager is None:
                    continue
                states_to_retry = await self.wallet_state_manager.retry_store.get_all_states_to_retry()
                for state, peer_id, fork_height in states_to_retry:
                    matching_peer = tuple(
                        p for p in self.server.get_connections(NodeType.FULL_NODE) if p.peer_node_id == peer_id
                    )
                    if len(matching_peer) == 0:
                        try:
                            peer = self.get_full_node_peer()
                            self.log.info(
                                f"disconnected from peer {peer_id}, state will retry with {peer.peer_node_id}"
                            )
                        except ValueError:
                            self.log.info(f"disconnected from all peers, cannot retry state: {state}")
                            continue
                    else:
                        peer = matching_peer[0]
                    async with self.wallet_state_manager.db_wrapper.writer():
                        self.log.info(f"retrying coin_state: {state}")
                        await self.wallet_state_manager.add_coin_states(
                            [state], peer, None if fork_height == 0 else fork_height
                        )
            except asyncio.CancelledError:
                self.log.info("Retry task cancelled, exiting.")
                raise

    async def _process_new_subscriptions(self) -> None:
        while not self._shut_down:
            # Here we process four types of messages in the queue, where the first one has higher priority (lower
            # number in the queue), and priority decreases for each type.
            peer: Optional[WSChiaConnection] = None
            item: Optional[NewPeakItem] = None
            try:
                peer, item = None, None
                item = await self.new_peak_queue.get()
                assert item is not None
                if item.item_type == NewPeakQueueTypes.COIN_ID_SUBSCRIPTION:
                    self.log.debug("Pulled from queue: %s %s", item.item_type.name, item.data)
                    # Subscriptions are the highest priority, because we don't want to process any more peaks or
                    # state updates until we are sure that we subscribed to everything that we need to. Otherwise,
                    # we might not be able to process some state.
                    coin_ids: List[bytes32] = item.data
                    for peer in self.server.get_connections(NodeType.FULL_NODE):
                        coin_states: List[CoinState] = await subscribe_to_coin_updates(coin_ids, peer, uint32(0))
                        if len(coin_states) > 0:
                            async with self.wallet_state_manager.lock:
                                await self.add_states_from_peer(coin_states, peer)
                elif item.item_type == NewPeakQueueTypes.PUZZLE_HASH_SUBSCRIPTION:
                    self.log.debug("Pulled from queue: %s %s", item.item_type.name, item.data)
                    puzzle_hashes: List[bytes32] = item.data
                    for peer in self.server.get_connections(NodeType.FULL_NODE):
                        # Puzzle hash subscription
                        coin_states = await subscribe_to_phs(puzzle_hashes, peer, uint32(0))
                        if len(coin_states) > 0:
                            async with self.wallet_state_manager.lock:
                                await self.add_states_from_peer(coin_states, peer)
                elif item.item_type == NewPeakQueueTypes.FULL_NODE_STATE_UPDATED:
                    # Note: this can take a while when we have a lot of transactions. We want to process these
                    # before new_peaks, since new_peak_wallet requires that we first obtain the state for that peak.
                    self.log.debug("Pulled from queue: %s %s", item.item_type.name, item.data[0])
                    coin_state_update = item.data[0]
                    peer = item.data[1]
                    assert peer is not None
                    await self.state_update_received(coin_state_update, peer)
                elif item.item_type == NewPeakQueueTypes.NEW_PEAK_WALLET:
                    self.log.debug("Pulled from queue: %s %s", item.item_type.name, item.data[0])
                    # This can take a VERY long time, because it might trigger a long sync. It is OK if we miss some
                    # subscriptions or state updates, since all subscriptions and state updates will be handled by
                    # long_sync (up to the target height).
                    new_peak = item.data[0]
                    peer = item.data[1]
                    assert peer is not None
                    await self.new_peak_wallet(new_peak, peer)
                    # Check if any coin needs auto spending
                    if self.config.get("auto_claim", {}).get("enabled", False):
                        await self.wallet_state_manager.auto_claim_coins()
                else:
                    self.log.debug("Pulled from queue: UNKNOWN %s", item.item_type)
                    assert False
            except asyncio.CancelledError:
                self.log.info("Queue task cancelled, exiting.")
                raise
            except Exception as e:
                self.log.error(f"Exception handling {item}, {e} {traceback.format_exc()}")
                if peer is not None:
                    await peer.close(9999)

    def log_in(self, sk: PrivateKey) -> None:
        self.logged_in_fingerprint = sk.get_g1().get_fingerprint()
        self.logged_in = True
        self.log.info(f"Wallet is logged in using key with fingerprint: {self.logged_in_fingerprint}")
        try:
            self.update_last_used_fingerprint()
        except Exception:
            self.log.exception("Non-fatal: Unable to update last used fingerprint.")

    def log_out(self) -> None:
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

    def set_server(self, server: ChiaServer) -> None:
        self._server = server
        self.initialize_wallet_peers()

    def initialize_wallet_peers(self) -> None:
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

    def on_disconnect(self, peer: WSChiaConnection) -> None:
        if self.is_trusted(peer):
            self.local_node_synced = False
            self.initialize_wallet_peers()

        if peer.peer_node_id in self.peer_caches:
            self.peer_caches.pop(peer.peer_node_id)
        if peer.peer_node_id in self.synced_peers:
            self.synced_peers.remove(peer.peer_node_id)
        if peer.peer_node_id in self.node_peaks:
            self.node_peaks.pop(peer.peer_node_id)

        self.wallet_state_manager.state_changed("close_connection")

    async def on_connect(self, peer: WSChiaConnection) -> None:
        if self._wallet_state_manager is None:
            return None

        if peer.protocol_version < Version("0.0.33"):
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

    async def perform_atomic_rollback(self, fork_height: int, cache: Optional[PeerRequestCache] = None) -> None:
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
    ) -> None:
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
        self.log.info(f"Starting sync trusted: {trusted} to peer {full_node.peer_info.host}")
        start_time = time.time()

        if rollback:
            # we should clear all peers since this is a full rollback
            await self.perform_atomic_rollback(fork_height)
            await self.update_ui()

        # We only process new state updates to avoid slow reprocessing. We set the sync height after adding
        # Things, so we don't have to reprocess these later. There can be many things in ph_update_res.
        already_checked_ph: Set[bytes32] = set()
        while not self._shut_down:
            await self.wallet_state_manager.create_more_puzzle_hashes()
            all_puzzle_hashes = await self.get_puzzle_hashes_to_subscribe()
            not_checked_puzzle_hashes = set(all_puzzle_hashes) - already_checked_ph
            if not_checked_puzzle_hashes == set():
                break
            for batch in to_batches(not_checked_puzzle_hashes, 1000):
                ph_update_res: List[CoinState] = await subscribe_to_phs(batch.entries, full_node, 0)
                ph_update_res = list(filter(is_new_state_update, ph_update_res))
                if not await self.add_states_from_peer(ph_update_res, full_node):
                    # If something goes wrong, abort sync
                    return
            already_checked_ph.update(not_checked_puzzle_hashes)

        self.log.info(f"Successfully subscribed and updated {len(already_checked_ph)} puzzle hashes")

        # The number of coin id updates are usually going to be significantly less than ph updates, so we can
        # sync from 0 every time.
        already_checked_coin_ids: Set[bytes32] = set()
        while not self._shut_down:
            all_coin_ids = await self.get_coin_ids_to_subscribe()
            not_checked_coin_ids = set(all_coin_ids) - already_checked_coin_ids
            if not_checked_coin_ids == set():
                break
            for batch in to_batches(not_checked_coin_ids, 1000):
                c_update_res: List[CoinState] = await subscribe_to_coin_updates(batch.entries, full_node, 0)

                if not await self.add_states_from_peer(c_update_res, full_node):
                    # If something goes wrong, abort sync
                    return
            already_checked_coin_ids.update(not_checked_coin_ids)
        self.log.info(f"Successfully subscribed and updated {len(already_checked_coin_ids)} coin ids")

        # Only update this fully when the entire sync has completed
        await self.wallet_state_manager.blockchain.set_finished_sync_up_to(target_height)

        if trusted:
            self.local_node_synced = True

        self.wallet_state_manager.state_changed("new_block")

        self.synced_peers.add(full_node.peer_node_id)
        await self.update_ui()

        self.log.info(f"Sync (trusted: {trusted}) duration was: {time.time() - start_time}")

    async def add_states_from_peer(
        self,
        items_input: List[CoinState],
        peer: WSChiaConnection,
        fork_height: Optional[uint32] = None,
        height: Optional[uint32] = None,
        header_hash: Optional[bytes32] = None,
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

        all_tasks: List[asyncio.Task[None]] = []
        target_concurrent_tasks: int = 30

        # Ensure the list is sorted
        unique_items = set(items_input)
        before = len(unique_items)
        items = await self.wallet_state_manager.filter_spam(sort_coin_states(unique_items))
        num_filtered = before - len(items)
        if num_filtered > 0:
            self.log.info(f"Filtered {num_filtered} spam transactions")

        async def validate_and_add(inner_states: List[CoinState], inner_idx_start: int) -> None:
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
                            await self.wallet_state_manager.add_coin_states(valid_states, peer, fork_height)
            except Exception as e:
                tb = traceback.format_exc()
                log_level = logging.DEBUG if peer.closed or self._shut_down else logging.ERROR
                self.log.log(log_level, f"validate_and_add failed - exception: {e}, traceback: {tb}")

        idx = 1
        # Keep chunk size below 1000 just in case, windows has sqlite limits of 999 per query
        # Untrusted has a smaller batch size since validation has to happen which takes a while
        chunk_size: int = 900 if trusted else 10
        for batch in to_batches(items, chunk_size):
            if self._server is None:
                self.log.error("No server")
                await asyncio.gather(*all_tasks)
                return False
            if peer.peer_node_id not in self.server.all_connections:
                self.log.error(f"Disconnected from peer {peer.peer_node_id} host {peer.peer_info.host}")
                await asyncio.gather(*all_tasks)
                return False
            if trusted:
                async with self.wallet_state_manager.db_wrapper.writer():
                    self.log.info(f"new coin state received ({idx}-{idx + len(batch.entries) - 1}/ {len(items)})")
                    if not await self.wallet_state_manager.add_coin_states(batch.entries, peer, fork_height):
                        return False
            else:
                while len(all_tasks) >= target_concurrent_tasks:
                    all_tasks = [task for task in all_tasks if not task.done()]
                    await asyncio.sleep(0.1)
                    if self._shut_down:
                        self.log.info("Terminating receipt and validation due to shut down request")
                        await asyncio.gather(*all_tasks)
                        return False
                all_tasks.append(asyncio.create_task(validate_and_add(batch.entries, idx)))
            idx += len(batch.entries)

        still_connected = self._server is not None and peer.peer_node_id in self.server.all_connections
        await asyncio.gather(*all_tasks)
        await self.update_ui()
        return still_connected and self._server is not None and peer.peer_node_id in self.server.all_connections

    async def is_peer_synced(self, peer: WSChiaConnection, height: uint32) -> Optional[uint64]:
        # Get last timestamp
        last_tx: Optional[HeaderBlock] = await fetch_last_tx_from_peer(height, peer)
        latest_timestamp: Optional[uint64] = None
        if last_tx is not None:
            assert last_tx.foliage_transaction_block is not None
            latest_timestamp = last_tx.foliage_transaction_block.timestamp

        # Return None if not synced
        if (
            latest_timestamp is None
            or self.config.get("testing", False) is False
            and latest_timestamp < uint64(time.time()) - 600
        ):
            return None
        return latest_timestamp

    def is_trusted(self, peer: WSChiaConnection) -> bool:
        return self.server.is_trusted_peer(peer, self.config.get("trusted_peers", {}))

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

    async def state_update_received(self, request: CoinStateUpdate, peer: WSChiaConnection) -> None:
        # This gets called every time there is a new coin or puzzle hash change in the DB
        # that is of interest to this wallet. It is not guaranteed to come for every height. This message is guaranteed
        # to come before the corresponding new_peak for each height. We handle this differently for trusted and
        # untrusted peers. For trusted, we always process the state, and we process reorgs as well.
        for coin in request.items:
            self.log.info(f"request coin: {coin.coin.name().hex()}{coin}")

        async with self.wallet_state_manager.lock:
            await self.add_states_from_peer(
                request.items,
                peer,
                request.fork_height,
                request.height,
                request.peak_hash,
            )

    def get_full_node_peer(self) -> WSChiaConnection:
        """
        Get a full node, preferring synced & trusted > synced & untrusted > unsynced & trusted > unsynced & untrusted
        """
        full_nodes: List[WSChiaConnection] = self.get_full_node_peers_in_order()
        if len(full_nodes) == 0:
            raise ValueError("No peer connected")
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

    async def get_timestamp_for_height(self, height: uint32) -> uint64:
        """
        Returns the timestamp for transaction block at h=height, if not transaction block, backtracks until it finds
        a transaction block
        """
        for cache in self.peer_caches.values():
            cache_ts: Optional[uint64] = cache.get_height_timestamp(height)
            if cache_ts is not None:
                return cache_ts

        for peer in self.get_full_node_peers_in_order():
            last_tx_block = await fetch_last_tx_from_peer(height, peer)
            if last_tx_block is None:
                continue

            assert last_tx_block.foliage_transaction_block is not None
            self.get_cache_for_peer(peer).add_to_blocks(last_tx_block)
            return last_tx_block.foliage_transaction_block.timestamp

        raise PeerRequestException("Error fetching timestamp from all peers")

    async def new_peak_wallet(self, new_peak: NewPeakWallet, peer: WSChiaConnection) -> None:
        if self._wallet_state_manager is None:
            # When logging out of wallet
            self.log.debug("state manager is None (shutdown)")
            return
        trusted: bool = self.is_trusted(peer)
        peak_hb: Optional[HeaderBlock] = await self.wallet_state_manager.blockchain.get_peak_block()
        if peak_hb is not None and new_peak.weight < peak_hb.weight:
            # Discards old blocks, but accepts blocks that are equal in weight to peak
            self.log.debug("skip block with lower weight.")
            return

        request = RequestBlockHeader(new_peak.height)
        response: Optional[RespondBlockHeader] = await peer.call_api(FullNodeAPI.request_block_header, request)
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

        latest_timestamp: Optional[uint64] = await self.is_peer_synced(peer, new_peak_hb.height)
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
            if not await self.new_peak_from_untrusted(new_peak_hb, peer):
                return

        if peer.peer_node_id in self.synced_peers:
            await self.wallet_state_manager.blockchain.set_finished_sync_up_to(new_peak.height)
        # todo why do we call this if there was an exception / the sync is not finished
        async with self.wallet_state_manager.lock:
            await self.wallet_state_manager.new_peak(new_peak)

    async def new_peak_from_trusted(
        self, new_peak_hb: HeaderBlock, latest_timestamp: uint64, peer: WSChiaConnection
    ) -> None:
        async with self.wallet_state_manager.set_sync_mode(new_peak_hb.height) as current_height:
            await self.wallet_state_manager.blockchain.set_peak_block(new_peak_hb, latest_timestamp)
            # Sync to trusted node if we haven't done so yet. As long as we have synced once (and not
            # disconnected), we assume that the full node will continue to give us state updates, so we do
            # not need to resync.
            if peer.peer_node_id not in self.synced_peers:
                await self.long_sync(new_peak_hb.height, peer, uint32(max(0, current_height - 256)), rollback=True)

    async def new_peak_from_untrusted(self, new_peak_hb: HeaderBlock, peer: WSChiaConnection) -> bool:
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

        secondary_sync_running = (
            self._secondary_peer_sync_task is not None and self._secondary_peer_sync_task.done() is False
        )
        if not syncing and secondary_sync_running:
            self.log.info("Will not do secondary sync, there is already another sync task running.")
            return False

        try:
            await self.long_sync_from_untrusted(syncing, new_peak_hb, peer)
        except Exception:
            self.log.exception(f"Error syncing to {peer.get_peer_info()}")
            await peer.close()
            return False
        return True

    async def long_sync_from_untrusted(self, syncing: bool, new_peak_hb: HeaderBlock, peer: WSChiaConnection) -> None:
        current_height: uint32 = await self.wallet_state_manager.blockchain.get_finished_sync_up_to()
        fork_point_weight_proof = await self.fetch_and_update_weight_proof(peer, new_peak_hb)
        # This usually happens the first time we start up the wallet. We roll back slightly to be
        # safe, but we don't want to rollback too much (hence 16)
        fork_point_rollback: int = max(0, current_height - 16)
        # If the weight proof fork point is in the past, rollback more to ensure we don't have duplicate
        fork_point_syncing = min(fork_point_rollback, fork_point_weight_proof)

        if syncing:
            async with self.wallet_state_manager.set_sync_mode(new_peak_hb.height):
                await self.long_sync(new_peak_hb.height, peer, fork_point_syncing, rollback=True)
            return

        # we exit earlier in the case where syncing is False and a Secondary sync is running
        assert self._secondary_peer_sync_task is None or self._secondary_peer_sync_task.done()
        self.log.info("Secondary peer syncing")
        # In this case we will not rollback so it's OK to check some older updates as well, to ensure
        # that no recent transactions are being hidden.
        self._secondary_peer_sync_task = asyncio.create_task(
            self.long_sync(new_peak_hb.height, peer, 0, rollback=False)
        )

    async def sync_from_untrusted_close_to_peak(self, new_peak_hb: HeaderBlock, peer: WSChiaConnection) -> bool:
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
                all_coin_ids: List[bytes32] = await self.get_coin_ids_to_subscribe()
                phs: List[bytes32] = await self.get_puzzle_hashes_to_subscribe()
                ph_updates: List[CoinState] = await subscribe_to_phs(phs, peer, uint32(0))
                coin_updates: List[CoinState] = await subscribe_to_coin_updates(all_coin_ids, peer, uint32(0))
                peer_new_peak = self.node_peaks[peer.peer_node_id]
                success = await self.add_states_from_peer(
                    ph_updates + coin_updates,
                    peer,
                    height=peer_new_peak.height,
                    header_hash=peer_new_peak.hash,
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
                    await self.add_states_from_peer(list(self.race_cache[header_hash]), peer)

            self.wallet_state_manager.state_changed("new_block")
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
            request_prev = RequestBlockHeader(uint32(top.height - 1))
            response_prev: Optional[RespondBlockHeader] = await peer.call_api(
                FullNodeAPI.request_block_header, request_prev
            )
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
            res, err = await self.wallet_state_manager.blockchain.add_block(block)
            if res == AddBlockResult.INVALID_BLOCK:
                raise ValueError(err)

        return fork_height

    async def update_ui(self) -> None:
        for wallet_id, wallet in self.wallet_state_manager.wallets.items():
            self.wallet_state_manager.state_changed("coin_removed", wallet_id)
            self.wallet_state_manager.state_changed("coin_added", wallet_id)

    async def fetch_and_update_weight_proof(self, peer: WSChiaConnection, peak: HeaderBlock) -> int:
        assert self._weight_proof_handler is not None
        weight_request = RequestProofOfWeight(peak.height, peak.header_hash)
        wp_timeout = self.config.get("weight_proof_timeout", 360)
        self.log.debug(f"weight proof timeout is {wp_timeout} sec")
        weight_proof_response: RespondProofOfWeight = await peer.call_api(
            FullNodeAPI.request_proof_of_weight, weight_request, timeout=wp_timeout
        )

        if weight_proof_response is None:
            raise Exception("weight proof response was none")

        weight_proof = weight_proof_response.wp

        if weight_proof.recent_chain_data[-1].height != peak.height:
            raise Exception("weight proof height does not match peak")
        if weight_proof.recent_chain_data[-1].weight != peak.weight:
            raise Exception("weight proof weight does not match peak")
        if weight_proof.recent_chain_data[-1].header_hash != peak.header_hash:
            raise Exception("weight proof peak hash does not match peak")

        old_proof = self.wallet_state_manager.blockchain.synced_weight_proof
        block_records = await self._weight_proof_handler.validate_weight_proof(weight_proof, False, old_proof)

        await self.wallet_state_manager.blockchain.new_valid_weight_proof(weight_proof, block_records)

        return get_wp_fork_point(self.constants, old_proof, weight_proof)

    async def get_puzzle_hashes_to_subscribe(self) -> List[bytes32]:
        all_puzzle_hashes = await self.wallet_state_manager.puzzle_store.get_all_puzzle_hashes(1)
        # Get all phs from interested store
        interested_puzzle_hashes = [
            t[0] for t in await self.wallet_state_manager.interested_store.get_interested_puzzle_hashes()
        ]
        all_puzzle_hashes.update(interested_puzzle_hashes)
        return list(all_puzzle_hashes)

    async def get_coin_ids_to_subscribe(self) -> List[bytes32]:
        coin_ids = await self.wallet_state_manager.trade_manager.get_coins_of_interest()
        coin_ids.update(await self.wallet_state_manager.interested_store.get_interested_coin_ids())
        return list(coin_ids)

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
        if peer.closed:
            return False
        # Only use the cache if we are talking about states before the fork point. If we are evaluating something
        # in a reorg, we cannot use the cache, since we don't know if it's actually in the new chain after the reorg.
        if can_use_peer_request_cache(coin_state, peer_request_cache, fork_height):
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
        start = uint32(block.height + 1)
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
            end = uint32(0)
            for idx, ses in enumerate(weight_proof.sub_epochs):
                if idx == len(weight_proof.sub_epochs) - 1:
                    break
                next_ses_height = uint32(
                    (idx + 1) * self.constants.SUB_EPOCH_BLOCKS + weight_proof.sub_epochs[idx + 1].num_blocks_overflow
                )
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
                        end = uint32(
                            (idx + 2) * self.constants.SUB_EPOCH_BLOCKS
                            + weight_proof.sub_epochs[idx + 2].num_blocks_overflow
                        )
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
            log_level = logging.DEBUG if self._shut_down or peer.closed else logging.ERROR
            self.log.log(log_level, f"Error fetching blocks {start} {end}")
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

    async def get_coin_state(
        self, coin_names: List[bytes32], peer: WSChiaConnection, fork_height: Optional[uint32] = None
    ) -> List[CoinState]:
        msg = RegisterForCoinUpdates(coin_names, uint32(0))
        coin_state: Optional[RespondToCoinUpdates] = await peer.call_api(FullNodeAPI.register_interest_in_coin, msg)
        if coin_state is None or not isinstance(coin_state, RespondToCoinUpdates):
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
        response: Optional[RespondChildren] = await peer.call_api(
            FullNodeAPI.request_children, RequestChildren(coin_name)
        )
        if response is None or not isinstance(response, RespondChildren):
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
    async def push_tx(self, spend_bundle: SpendBundle) -> None:
        msg = make_msg(ProtocolMessageTypes.send_transaction, SendTransaction(spend_bundle))
        full_nodes = self.server.get_connections(NodeType.FULL_NODE)
        for peer in full_nodes:
            await peer.send_message(msg)

    async def _update_balance_cache(self, wallet_id: uint32) -> None:
        assert self.wallet_state_manager.lock.locked(), "WalletStateManager.lock required"
        wallet = self.wallet_state_manager.wallets[wallet_id]
        unspent_records = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(wallet_id)
        balance = await wallet.get_confirmed_balance(unspent_records)
        pending_balance = await wallet.get_unconfirmed_balance(unspent_records)
        spendable_balance = await wallet.get_spendable_balance(unspent_records)
        pending_change = await wallet.get_pending_change_balance()
        max_send_amount = await wallet.get_max_send_amount(unspent_records)

        unconfirmed_removals: Dict[bytes32, Coin] = await wallet.wallet_state_manager.unconfirmed_removals_for_wallet(
            wallet_id
        )
        self._balance_cache[wallet_id] = Balance(
            confirmed_wallet_balance=balance,
            unconfirmed_wallet_balance=pending_balance,
            spendable_balance=spendable_balance,
            pending_change=pending_change,
            max_send_amount=max_send_amount,
            unspent_coin_count=uint32(len(unspent_records)),
            pending_coin_removal_count=uint32(len(unconfirmed_removals)),
        )

    async def get_balance(self, wallet_id: uint32) -> Balance:
        self.log.debug(f"get_balance - wallet_id: {wallet_id}")
        if not self.wallet_state_manager.sync_mode:
            self.log.debug(f"get_balance - Updating cache for {wallet_id}")
            async with self.wallet_state_manager.lock:
                await self._update_balance_cache(wallet_id)
        return self._balance_cache.get(wallet_id, Balance())
