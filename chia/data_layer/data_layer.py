from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import functools
import json
import logging
import os
import random
import time
import traceback
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    ClassVar,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
    cast,
    final,
)

import aiohttp

from chia.data_layer.data_layer_errors import KeyNotFoundError
from chia.data_layer.data_layer_util import (
    DiffData,
    InternalNode,
    KeysPaginationData,
    KeysValuesPaginationData,
    KeyValue,
    KVDiffPaginationData,
    Layer,
    Offer,
    OfferStore,
    PluginRemote,
    PluginStatus,
    Proof,
    ProofOfInclusion,
    ProofOfInclusionLayer,
    Root,
    ServerInfo,
    Status,
    StoreProofs,
    Subscription,
    SyncStatus,
    TerminalNode,
    Unspecified,
    UnsubscribeData,
    leaf_hash,
    unspecified,
)
from chia.data_layer.data_layer_wallet import DataLayerWallet, Mirror, SingletonRecord, verify_offer
from chia.data_layer.data_store import DataStore
from chia.data_layer.download_data import (
    delete_full_file_if_exists,
    get_delta_filename_path,
    get_full_tree_filename_path,
    insert_from_delta_file,
    write_files_for_root,
)
from chia.rpc.rpc_server import StateChangedProtocol, default_get_connections
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.async_pool import Job, QueuedAsyncPool
from chia.util.ints import uint32, uint64
from chia.util.path import path_from_root
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer as TradingOffer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG


async def get_plugin_info(plugin_remote: PluginRemote) -> Tuple[PluginRemote, Dict[str, Any]]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                plugin_remote.url + "/plugin_info",
                json={},
                headers=plugin_remote.headers,
            ) as response:
                ret = {"status": response.status}
                if response.status == 200:
                    ret["response"] = json.loads(await response.text())
                return plugin_remote, ret
    except aiohttp.ClientError as e:
        return plugin_remote, {"error": f"ClientError: {e}"}


@final
@dataclasses.dataclass
class DataLayer:
    if TYPE_CHECKING:
        from chia.rpc.rpc_server import RpcServiceProtocol

        _protocol_check: ClassVar[RpcServiceProtocol] = cast("DataLayer", None)

    db_path: Path
    config: Dict[str, Any]
    root_path: Path
    log: logging.Logger
    wallet_rpc_init: Awaitable[WalletRpcClient]
    downloaders: List[PluginRemote]
    uploaders: List[PluginRemote]
    maximum_full_file_count: int
    server_files_location: Path
    unsubscribe_data_queue: List[UnsubscribeData]
    _server: Optional[ChiaServer] = None
    none_bytes: bytes32 = bytes32([0] * 32)
    initialized: bool = False
    _data_store: Optional[DataStore] = None
    state_changed_callback: Optional[StateChangedProtocol] = None
    _shut_down: bool = False
    periodically_manage_data_task: Optional[asyncio.Task[None]] = None
    _wallet_rpc: Optional[WalletRpcClient] = None
    subscription_lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)
    subscription_update_concurrency: int = 5
    client_timeout: aiohttp.ClientTimeout = dataclasses.field(
        default_factory=functools.partial(aiohttp.ClientTimeout, total=45, sock_connect=5)
    )
    group_files_by_store: bool = False

    @property
    def server(self) -> ChiaServer:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._server is None:
            raise RuntimeError("server not assigned")

        return self._server

    @property
    def data_store(self) -> DataStore:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._data_store is None:
            raise RuntimeError("data_store not assigned")

        return self._data_store

    @property
    def wallet_rpc(self) -> WalletRpcClient:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._wallet_rpc is None:
            raise RuntimeError("wallet_rpc not assigned")

        return self._wallet_rpc

    @classmethod
    def create(
        cls,
        config: Dict[str, Any],
        root_path: Path,
        wallet_rpc_init: Awaitable[WalletRpcClient],
        downloaders: List[PluginRemote],
        uploaders: List[PluginRemote],  # dont add FilesystemUploader to this, it is the default uploader
        name: Optional[str] = None,
    ) -> DataLayer:
        if name == "":
            # TODO: If no code depends on "" counting as 'unspecified' then we do not
            #       need this.
            name = None

        server_files_replaced: str = config.get(
            "server_files_location", "data_layer/db/server_files_location_CHALLENGE"
        ).replace("CHALLENGE", config["selected_network"])

        db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])

        self = cls(
            config=config,
            root_path=root_path,
            wallet_rpc_init=wallet_rpc_init,
            log=logging.getLogger(name if name is None else __name__),
            db_path=path_from_root(root_path, db_path_replaced),
            server_files_location=path_from_root(root_path, server_files_replaced),
            downloaders=downloaders,
            uploaders=uploaders,
            maximum_full_file_count=config.get("maximum_full_file_count", 1),
            subscription_update_concurrency=config.get("subscription_update_concurrency", 5),
            unsubscribe_data_queue=[],
            client_timeout=aiohttp.ClientTimeout(
                total=config.get("client_timeout", 45), sock_connect=config.get("connect_timeout", 5)
            ),
            group_files_by_store=config.get("group_files_by_store", False),
        )

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.server_files_location.mkdir(parents=True, exist_ok=True)

        return self

    @contextlib.asynccontextmanager
    async def manage(self) -> AsyncIterator[None]:
        sql_log_path: Optional[Path] = None
        if self.config.get("log_sqlite_cmds", False):
            sql_log_path = path_from_root(self.root_path, "log/data_sql.log")
            self.log.info(f"logging SQL commands to {sql_log_path}")

        async with DataStore.managed(database=self.db_path, sql_log_path=sql_log_path) as self._data_store:
            self._wallet_rpc = await self.wallet_rpc_init

            await self._data_store.migrate_db()
            self.periodically_manage_data_task = asyncio.create_task(self.periodically_manage_data())
            try:
                yield
            finally:
                # TODO: review for anything else we need to do here
                self._shut_down = True
                if self._wallet_rpc is not None:
                    self.wallet_rpc.close()

                if self.periodically_manage_data_task is not None:
                    try:
                        self.periodically_manage_data_task.cancel()
                    except asyncio.CancelledError:
                        pass
                if self._wallet_rpc is not None:
                    await self.wallet_rpc.await_closed()

    def _set_state_changed_callback(self, callback: StateChangedProtocol) -> None:
        self.state_changed_callback = callback

    async def on_connect(self, connection: WSChiaConnection) -> None:
        pass

    def get_connections(self, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

    def set_server(self, server: ChiaServer) -> None:
        self._server = server

    async def wallet_log_in(self, fingerprint: int) -> int:
        result = await self.wallet_rpc.log_in(fingerprint)
        if not result.get("success", False):
            wallet_error = result.get("error", "no error message provided")
            raise Exception(f"DataLayer wallet RPC log in request failed: {wallet_error}")

        fingerprint = cast(int, result["fingerprint"])
        return fingerprint

    async def create_store(
        self, fee: uint64, root: bytes32 = bytes32([0] * 32)
    ) -> Tuple[List[TransactionRecord], bytes32]:
        txs, store_id = await self.wallet_rpc.create_new_dl(root, fee)
        res = await self.data_store.create_tree(store_id=store_id)
        if res is None:
            self.log.fatal("failed creating store")
        self.initialized = True
        return txs, store_id

    async def batch_update(
        self,
        store_id: bytes32,
        changelist: List[Dict[str, Any]],
        fee: uint64,
        submit_on_chain: bool = True,
    ) -> Optional[TransactionRecord]:
        status = Status.PENDING if submit_on_chain else Status.PENDING_BATCH
        await self.batch_insert(store_id=store_id, changelist=changelist, status=status)
        await self.data_store.clean_node_table()

        if submit_on_chain:
            return await self.publish_update(store_id=store_id, fee=fee)
        else:
            return None

    async def _get_publishable_root_hash(self, store_id: bytes32) -> bytes32:
        pending_root: Optional[Root] = await self.data_store.get_pending_root(store_id=store_id)
        if pending_root is None:
            raise Exception("Latest root is already confirmed.")
        if pending_root.status == Status.PENDING_BATCH:
            raise Exception("Unable to publish on chain, batch update set still open.")

        return self.none_bytes if pending_root.node_hash is None else pending_root.node_hash

    async def multistore_batch_update(
        self,
        store_updates: List[Dict[str, Any]],
        fee: uint64,
        submit_on_chain: bool = True,
    ) -> List[TransactionRecord]:
        store_ids: Set[bytes32] = set()
        for update in store_updates:
            store_id = update["store_id"]
            changelist = update["changelist"]

            if store_id in store_ids:
                raise Exception(f"Store id {store_id.hex()} must appear in a single update")
            store_ids.add(store_id)

            status = Status.PENDING if submit_on_chain else Status.PENDING_BATCH
            await self.batch_insert(store_id=store_id, changelist=changelist, status=status)

        await self.data_store.clean_node_table()

        if submit_on_chain:
            update_dictionary: Dict[bytes32, bytes32] = {}
            for store_id in store_ids:
                await self._update_confirmation_status(store_id=store_id)
                root_hash = await self._get_publishable_root_hash(store_id=store_id)
                update_dictionary[store_id] = root_hash
            transaction_records = await self.wallet_rpc.dl_update_multiple(update_dictionary=update_dictionary, fee=fee)
            return transaction_records
        else:
            return []

    async def submit_pending_root(
        self,
        store_id: bytes32,
        fee: uint64,
    ) -> TransactionRecord:
        await self._update_confirmation_status(store_id=store_id)

        pending_root: Optional[Root] = await self.data_store.get_pending_root(store_id=store_id)
        if pending_root is None:
            raise Exception("Latest root is already confirmed.")
        if pending_root.status == Status.PENDING:
            raise Exception("Pending root is already submitted.")

        await self.data_store.change_root_status(pending_root, Status.PENDING)
        return await self.publish_update(store_id, fee)

    async def submit_all_pending_roots(self, fee: uint64) -> List[TransactionRecord]:
        pending_roots = await self.data_store.get_all_pending_batches_roots()
        update_dictionary: Dict[bytes32, bytes32] = {}
        if len(pending_roots) == 0:
            raise Exception("No pending roots found to submit")
        for pending_root in pending_roots:
            root_hash = pending_root.node_hash if pending_root.node_hash is not None else self.none_bytes
            update_dictionary[pending_root.store_id] = root_hash
            await self.data_store.change_root_status(pending_root, Status.PENDING)
        transaction_records = await self.wallet_rpc.dl_update_multiple(update_dictionary=update_dictionary, fee=fee)
        return transaction_records

    async def batch_insert(
        self,
        store_id: bytes32,
        changelist: List[Dict[str, Any]],
        status: Status = Status.PENDING,
        enable_batch_autoinsert: Optional[bool] = None,
    ) -> bytes32:
        await self._update_confirmation_status(store_id=store_id)

        async with self.data_store.transaction():
            pending_root: Optional[Root] = await self.data_store.get_pending_root(store_id=store_id)
            if pending_root is not None and pending_root.status == Status.PENDING:
                raise Exception("Already have a pending root waiting for confirmation.")

            # check before any DL changes that this singleton is currently owned by this wallet
            singleton_records: List[SingletonRecord] = await self.get_owned_stores()
            if not any(store_id == singleton.launcher_id for singleton in singleton_records):
                raise ValueError(f"Singleton with launcher ID {store_id} is not owned by DL Wallet")

            t1 = time.monotonic()
            if enable_batch_autoinsert is None:
                enable_batch_autoinsert = self.config.get("enable_batch_autoinsert", True)
            batch_hash = await self.data_store.insert_batch(store_id, changelist, status, enable_batch_autoinsert)
            t2 = time.monotonic()
            self.log.info(f"Data store batch update process time: {t2 - t1}.")
            # todo return empty node hash from get_tree_root
            if batch_hash is not None:
                node_hash = batch_hash
            else:
                node_hash = self.none_bytes  # todo change

            return node_hash

    async def publish_update(
        self,
        store_id: bytes32,
        fee: uint64,
    ) -> TransactionRecord:
        await self._update_confirmation_status(store_id=store_id)
        root_hash = await self._get_publishable_root_hash(store_id=store_id)
        transaction_record = await self.wallet_rpc.dl_update_root(
            launcher_id=store_id,
            new_root=root_hash,
            fee=fee,
        )
        return transaction_record

    async def get_key_value_hash(
        self,
        store_id: bytes32,
        key: bytes,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> bytes32:
        await self._update_confirmation_status(store_id=store_id)

        async with self.data_store.transaction():
            node = await self.data_store.get_node_by_key(store_id=store_id, key=key, root_hash=root_hash)
            return node.hash

    async def get_value(
        self, store_id: bytes32, key: bytes, root_hash: Union[bytes32, Unspecified] = unspecified
    ) -> bytes:
        await self._update_confirmation_status(store_id=store_id)

        async with self.data_store.transaction():
            # this either returns the node or raises an exception
            res = await self.data_store.get_node_by_key(store_id=store_id, key=key, root_hash=root_hash)
            return res.value

    async def get_keys_values(
        self,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified],
    ) -> List[TerminalNode]:
        await self._update_confirmation_status(store_id=store_id)

        res = await self.data_store.get_keys_values(store_id, root_hash)
        if res is None:
            self.log.error("Failed to fetch keys values")
        return res

    async def get_keys_values_paginated(
        self,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified],
        page: int,
        max_page_size: Optional[int] = None,
    ) -> KeysValuesPaginationData:
        await self._update_confirmation_status(store_id=store_id)

        if max_page_size is None:
            max_page_size = 40 * 1024 * 1024
        res = await self.data_store.get_keys_values_paginated(store_id, page, max_page_size, root_hash)
        return res

    async def get_keys(self, store_id: bytes32, root_hash: Union[bytes32, Unspecified]) -> List[bytes]:
        await self._update_confirmation_status(store_id=store_id)

        res = await self.data_store.get_keys(store_id, root_hash)
        return res

    async def get_keys_paginated(
        self,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified],
        page: int,
        max_page_size: Optional[int] = None,
    ) -> KeysPaginationData:
        await self._update_confirmation_status(store_id=store_id)

        if max_page_size is None:
            max_page_size = 40 * 1024 * 1024
        res = await self.data_store.get_keys_paginated(store_id, page, max_page_size, root_hash)
        return res

    async def get_ancestors(self, node_hash: bytes32, store_id: bytes32) -> List[InternalNode]:
        await self._update_confirmation_status(store_id=store_id)

        res = await self.data_store.get_ancestors(node_hash=node_hash, store_id=store_id)
        if res is None:
            self.log.error("Failed to get ancestors")
        return res

    async def get_root(self, store_id: bytes32) -> Optional[SingletonRecord]:
        latest = await self.wallet_rpc.dl_latest_singleton(store_id, True)
        if latest is None:
            self.log.error(f"Failed to get root for {store_id.hex()}")
        return latest

    async def get_local_root(self, store_id: bytes32) -> Optional[bytes32]:
        await self._update_confirmation_status(store_id=store_id)

        res = await self.data_store.get_tree_root(store_id=store_id)
        if res is None:
            self.log.error(f"Failed to get root for {store_id.hex()}")
            return None
        return res.node_hash

    async def get_root_history(self, store_id: bytes32) -> List[SingletonRecord]:
        records = await self.wallet_rpc.dl_history(store_id)
        if records is None:
            self.log.error(f"Failed to get root history for {store_id.hex()}")
        root_history = []
        prev: Optional[SingletonRecord] = None
        for record in records:
            if prev is None or record.root != prev.root:
                root_history.append(record)
                prev = record
        return root_history

    async def _update_confirmation_status(self, store_id: bytes32) -> None:
        async with self.data_store.transaction():
            try:
                root = await self.data_store.get_tree_root(store_id=store_id)
            except Exception:
                root = None
            singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(store_id, True)
            if singleton_record is None:
                return
            if root is None:
                pending_root = await self.data_store.get_pending_root(store_id=store_id)
                if pending_root is not None and pending_root.status == Status.PENDING:
                    if pending_root.generation == 0 and pending_root.node_hash is None:
                        await self.data_store.change_root_status(pending_root, Status.COMMITTED)
                        await self.data_store.clear_pending_roots(store_id=store_id)
                        return
                    else:
                        root = None
            if root is None:
                self.log.info(f"Don't have pending root for {store_id}.")
                return
            if root.generation == singleton_record.generation:
                return
            if root.generation > singleton_record.generation:
                self.log.info(
                    f"Local root ahead of chain root: {root.generation} {singleton_record.generation}. "
                    "Maybe we're doing a batch update."
                )
                return
            wallet_history = await self.wallet_rpc.dl_history(
                launcher_id=store_id,
                min_generation=uint32(root.generation + 1),
                max_generation=singleton_record.generation,
            )
            new_hashes = [record.root for record in reversed(wallet_history)]
            root_hash = self.none_bytes if root.node_hash is None else root.node_hash
            generation_shift = 0
            while len(new_hashes) > 0 and new_hashes[0] == root_hash:
                generation_shift += 1
                new_hashes.pop(0)
            if generation_shift > 0:
                await self.data_store.clear_pending_roots(store_id=store_id)
                await self.data_store.shift_root_generations(store_id=store_id, shift_size=generation_shift)
            else:
                expected_root_hash = None if new_hashes[0] == self.none_bytes else new_hashes[0]
                pending_root = await self.data_store.get_pending_root(store_id=store_id)
                if (
                    pending_root is not None
                    and pending_root.generation == root.generation + 1
                    and pending_root.node_hash == expected_root_hash
                    and pending_root.status == Status.PENDING
                ):
                    await self.data_store.change_root_status(pending_root, Status.COMMITTED)
                    await self.data_store.build_ancestor_table_for_latest_root(store_id=store_id)
            await self.data_store.clear_pending_roots(store_id=store_id)

    async def fetch_and_validate(self, store_id: bytes32) -> None:
        singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(store_id, True)
        if singleton_record is None:
            self.log.info(f"Fetch data: No singleton record for {store_id}.")
            return
        if singleton_record.generation == uint32(0):
            self.log.info(f"Fetch data: No data on chain for {store_id}.")
            return

        await self._update_confirmation_status(store_id=store_id)

        if not await self.data_store.store_id_exists(store_id=store_id):
            await self.data_store.create_tree(store_id=store_id, status=Status.COMMITTED)

        timestamp = int(time.time())
        servers_info = await self.data_store.get_available_servers_for_store(store_id, timestamp)
        # TODO: maybe append a random object to the whole DataLayer class?
        random.shuffle(servers_info)
        for server_info in servers_info:
            url = server_info.url

            root = await self.data_store.get_tree_root(store_id=store_id)
            if root.generation > singleton_record.generation:
                self.log.info(
                    "Fetch data: local DL store is ahead of chain generation. "
                    f"Local root: {root}. Singleton: {singleton_record}"
                )
                break
            if root.generation == singleton_record.generation:
                self.log.info(f"Fetch data: wallet generation matching on-chain generation: {store_id}.")
                break

            self.log.info(
                f"Downloading files {store_id}. "
                f"Current wallet generation: {root.generation}. "
                f"Target wallet generation: {singleton_record.generation}. "
                f"Server used: {url}."
            )

            to_download = await self.wallet_rpc.dl_history(
                launcher_id=store_id,
                min_generation=uint32(root.generation + 1),
                max_generation=singleton_record.generation,
            )
            try:
                proxy_url = self.config.get("proxy_url", None)
                success = await insert_from_delta_file(
                    self.data_store,
                    store_id,
                    root.generation,
                    [record.root for record in reversed(to_download)],
                    server_info,
                    self.server_files_location,
                    self.client_timeout,
                    self.log,
                    proxy_url,
                    await self.get_downloader(store_id, url),
                    self.group_files_by_store,
                )
                if success:
                    self.log.info(
                        f"Finished downloading and validating {store_id}. "
                        f"Wallet generation saved: {singleton_record.generation}. "
                        f"Root hash saved: {singleton_record.root}."
                    )
                    break
            except aiohttp.client_exceptions.ClientConnectorError:
                self.log.warning(f"Server {url} unavailable for {store_id}.")
            except Exception as e:
                self.log.warning(f"Exception while downloading files for {store_id}: {e} {traceback.format_exc()}.")

    async def get_downloader(self, store_id: bytes32, url: str) -> Optional[PluginRemote]:
        request_json = {"store_id": store_id.hex(), "url": url}
        for d in self.downloaders:
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(
                        d.url + "/handle_download",
                        json=request_json,
                        headers=d.headers,
                    ) as response:
                        res_json = await response.json()
                        if res_json["handle_download"]:
                            return d
                except Exception as e:
                    self.log.error(f"get_downloader could not get response: {type(e).__name__}: {e}")
        return None

    async def clean_old_full_tree_files(self, store_id: bytes32) -> None:
        singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(store_id, True)
        if singleton_record is None:
            return
        await self._update_confirmation_status(store_id=store_id)

        root = await self.data_store.get_tree_root(store_id=store_id)
        latest_generation = root.generation
        full_tree_first_publish_generation = max(0, latest_generation - self.maximum_full_file_count + 1)
        foldername = self.server_files_location

        for generation in range(full_tree_first_publish_generation - 1, 0, -1):
            root = await self.data_store.get_tree_root(store_id=store_id, generation=generation)
            file_exists = delete_full_file_if_exists(foldername, store_id, root)
            if not file_exists:
                break

    async def upload_files(self, store_id: bytes32) -> None:
        uploaders = await self.get_uploaders(store_id)
        singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(store_id, True)
        if singleton_record is None:
            self.log.info(f"Upload files: no on-chain record for {store_id}.")
            return
        await self._update_confirmation_status(store_id=store_id)

        root = await self.data_store.get_tree_root(store_id=store_id)
        latest_generation = root.generation
        # Don't store full tree files before this generation.
        full_tree_first_publish_generation = max(0, latest_generation - self.maximum_full_file_count + 1)
        publish_generation = min(singleton_record.generation, 0 if root is None else root.generation)
        # If we make some batch updates, which get confirmed to the chain, we need to create the files.
        # We iterate back and write the missing files, until we find the files already written.
        root = await self.data_store.get_tree_root(store_id=store_id, generation=publish_generation)
        while publish_generation > 0:
            write_file_result = await write_files_for_root(
                self.data_store,
                store_id,
                root,
                self.server_files_location,
                full_tree_first_publish_generation,
                group_by_store=self.group_files_by_store,
            )
            if not write_file_result.result:
                # this particular return only happens if the files already exist, no need to log anything
                break
            try:
                if uploaders is not None and len(uploaders) > 0:
                    request_json = {
                        "store_id": store_id.hex(),
                        "diff_filename": write_file_result.diff_tree.name,
                        "group_files_by_store": self.group_files_by_store,
                    }
                    if write_file_result.full_tree is not None:
                        request_json["full_tree_filename"] = write_file_result.full_tree.name

                    for uploader in uploaders:
                        self.log.info(f"Using uploader {uploader} for store {store_id.hex()}")
                        async with aiohttp.ClientSession() as session:
                            async with session.post(
                                uploader.url + "/upload",
                                json=request_json,
                                headers=uploader.headers,
                            ) as response:
                                res_json = await response.json()
                                if res_json["uploaded"]:
                                    self.log.info(
                                        f"Uploaded files to {uploader} for store {store_id.hex()} "
                                        f"generation {publish_generation}"
                                    )
                                else:
                                    self.log.error(
                                        f"Failed to upload files to, will retry later: {uploader} : {res_json}"
                                    )
            except Exception as e:
                self.log.error(f"Exception uploading files, will retry later: store id {store_id}")
                self.log.debug(f"Failed to upload files, cleaning local files: {type(e).__name__}: {e}")
                if write_file_result.full_tree is not None:
                    os.remove(write_file_result.full_tree)
                os.remove(write_file_result.diff_tree)
            publish_generation -= 1
            root = await self.data_store.get_tree_root(store_id=store_id, generation=publish_generation)

    async def add_missing_files(self, store_id: bytes32, overwrite: bool, foldername: Optional[Path]) -> None:
        root = await self.data_store.get_tree_root(store_id=store_id)
        latest_generation = root.generation
        full_tree_first_publish_generation = max(0, latest_generation - self.maximum_full_file_count + 1)
        singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(store_id, True)
        if singleton_record is None:
            self.log.error(f"No singleton record found for: {store_id}")
            return
        max_generation = min(singleton_record.generation, 0 if root is None else root.generation)
        server_files_location = foldername if foldername is not None else self.server_files_location
        files = []
        for generation in range(1, max_generation + 1):
            root = await self.data_store.get_tree_root(store_id=store_id, generation=generation)
            res = await write_files_for_root(
                self.data_store,
                store_id,
                root,
                server_files_location,
                full_tree_first_publish_generation,
                overwrite,
                self.group_files_by_store,
            )
            files.append(res.diff_tree.name)
            if res.full_tree is not None:
                files.append(res.full_tree.name)

        uploaders = await self.get_uploaders(store_id)
        if uploaders is not None and len(uploaders) > 0:
            request_json = {
                "store_id": store_id.hex(),
                "files": json.dumps(files),
                "group_files_by_store": self.group_files_by_store,
            }
            for uploader in uploaders:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        uploader.url + "/add_missing_files",
                        json=request_json,
                        headers=uploader.headers,
                    ) as response:
                        res_json = await response.json()
                        if not res_json["uploaded"]:
                            self.log.error(f"failed to upload to uploader {uploader}")
                        else:
                            self.log.debug(f"uploaded to uploader {uploader}")

    async def subscribe(self, store_id: bytes32, urls: List[str]) -> Subscription:
        parsed_urls = [url.rstrip("/") for url in urls]
        subscription = Subscription(store_id, [ServerInfo(url, 0, 0) for url in parsed_urls])
        await self.wallet_rpc.dl_track_new(subscription.store_id)
        async with self.subscription_lock:
            await self.data_store.subscribe(subscription)
        self.log.info(f"Done adding subscription: {subscription.store_id}")
        return subscription

    async def remove_subscriptions(self, store_id: bytes32, urls: List[str]) -> None:
        parsed_urls = [url.rstrip("/") for url in urls]
        async with self.subscription_lock:
            await self.data_store.remove_subscriptions(store_id, parsed_urls)

    async def unsubscribe(self, store_id: bytes32, retain_data: bool) -> None:
        async with self.subscription_lock:
            subscriptions = await self.data_store.get_subscriptions()
            if store_id not in (subscription.store_id for subscription in subscriptions):
                raise RuntimeError("No subscription found for the given store_id.")

            # Unsubscribe is processed later, after all fetching of data is done, to avoid races.
            self.unsubscribe_data_queue.append(UnsubscribeData(store_id, retain_data))

    async def process_unsubscribe(self, store_id: bytes32, retain_data: bool) -> None:
        # This function already acquired `subscriptions_lock`.
        subscriptions = await self.data_store.get_subscriptions()
        if store_id not in (subscription.store_id for subscription in subscriptions):
            raise RuntimeError("No subscription found for the given store_id.")
        paths: List[Path] = []
        if await self.data_store.store_id_exists(store_id) and not retain_data:
            generation = await self.data_store.get_tree_generation(store_id)
            all_roots = await self.data_store.get_roots_between(store_id, 1, generation + 1)
            for root in all_roots:
                root_hash = root.node_hash if root.node_hash is not None else self.none_bytes
                for group_by_store in (True, False):
                    paths.append(
                        get_full_tree_filename_path(
                            self.server_files_location,
                            store_id,
                            root_hash,
                            root.generation,
                            group_by_store,
                        )
                    )
                    paths.append(
                        get_delta_filename_path(
                            self.server_files_location,
                            store_id,
                            root_hash,
                            root.generation,
                            group_by_store,
                        )
                    )

        # stop tracking first, then unsubscribe from the data store
        await self.wallet_rpc.dl_stop_tracking(store_id)
        await self.data_store.unsubscribe(store_id)
        if not retain_data:
            await self.data_store.delete_store_data(store_id)

        self.log.info(f"Unsubscribed to {store_id}")
        for file_path in paths:
            try:
                file_path.unlink()
            except FileNotFoundError:
                pass

    async def get_subscriptions(self) -> List[Subscription]:
        async with self.subscription_lock:
            return await self.data_store.get_subscriptions()

    async def add_mirror(self, store_id: bytes32, urls: List[str], amount: uint64, fee: uint64) -> None:
        if not urls:
            raise RuntimeError("URL list can't be empty")
        bytes_urls = [bytes(url, "utf8") for url in urls]
        await self.wallet_rpc.dl_new_mirror(store_id, amount, bytes_urls, fee)

    async def delete_mirror(self, coin_id: bytes32, fee: uint64) -> None:
        await self.wallet_rpc.dl_delete_mirror(coin_id, fee)

    async def get_mirrors(self, store_id: bytes32) -> List[Mirror]:
        mirrors: List[Mirror] = await self.wallet_rpc.dl_get_mirrors(store_id)
        return [mirror for mirror in mirrors if mirror.urls]

    async def update_subscriptions_from_wallet(self, store_id: bytes32) -> None:
        mirrors: List[Mirror] = await self.wallet_rpc.dl_get_mirrors(store_id)
        urls: List[str] = []
        for mirror in mirrors:
            urls = urls + [url.decode("utf8") for url in mirror.urls]
        urls = [url.rstrip("/") for url in urls]
        await self.data_store.update_subscriptions_from_wallet(store_id, urls)

    async def get_owned_stores(self) -> List[SingletonRecord]:
        return await self.wallet_rpc.dl_owned_singletons()

    async def get_kv_diff(self, store_id: bytes32, hash_1: bytes32, hash_2: bytes32) -> Set[DiffData]:
        return await self.data_store.get_kv_diff(store_id, hash_1, hash_2)

    async def get_kv_diff_paginated(
        self,
        store_id: bytes32,
        # NOTE: empty is expressed as zeros
        hash_1: bytes32,
        hash_2: bytes32,
        page: int,
        max_page_size: Optional[int] = None,
    ) -> KVDiffPaginationData:
        if max_page_size is None:
            max_page_size = 40 * 1024 * 1024
        return await self.data_store.get_kv_diff_paginated(store_id, page, max_page_size, hash_1, hash_2)

    async def periodically_manage_data(self) -> None:
        manage_data_interval = self.config.get("manage_data_interval", 60)
        while not self._shut_down:
            async with self.subscription_lock:
                try:
                    subscriptions = await self.data_store.get_subscriptions()
                    for subscription in subscriptions:
                        await self.wallet_rpc.dl_track_new(subscription.store_id)
                    break
                except aiohttp.client_exceptions.ClientConnectorError:
                    pass
                except Exception as e:
                    self.log.error(f"Exception while requesting wallet track subscription: {type(e)} {e}")

            self.log.warning("Cannot connect to the wallet. Retrying in 3s.")

            delay_until = time.monotonic() + 3
            while time.monotonic() < delay_until:
                if self._shut_down:
                    break
                await asyncio.sleep(0.1)

        while not self._shut_down:
            # Add existing subscriptions
            async with self.subscription_lock:
                subscriptions = await self.data_store.get_subscriptions()

            # pseudo-subscribe to all unsubscribed owned stores
            # Need this to make sure we process updates and generate DAT files
            try:
                owned_stores = await self.get_owned_stores()
            except ValueError:
                # Sometimes the DL wallet isn't available, so we can't get the owned stores.
                # We'll try again next time.
                owned_stores = []
            subscription_store_ids = {subscription.store_id for subscription in subscriptions}
            for record in owned_stores:
                store_id = record.launcher_id
                if store_id not in subscription_store_ids:
                    try:
                        # don't actually subscribe, just add to the list
                        subscriptions.insert(0, Subscription(store_id=store_id, servers_info=[]))
                    except Exception as e:
                        self.log.info(
                            f"Can't subscribe to owned store {store_id}: {type(e)} {e} {traceback.format_exc()}"
                        )

            # Optionally
            # Subscribe to all local non-owned store_ids that we can find on chain.
            # This is the prior behavior where all local stores, both owned and not owned, are subscribed to.
            if self.config.get("auto_subscribe_to_local_stores", False):
                local_store_ids = await self.data_store.get_store_ids()
                subscription_store_ids = {subscription.store_id for subscription in subscriptions}
                for local_id in local_store_ids:
                    if local_id not in subscription_store_ids:
                        try:
                            subscription = await self.subscribe(local_id, [])
                            subscriptions.insert(0, subscription)
                        except Exception as e:
                            self.log.info(
                                f"Can't subscribe to local store {local_id}: {type(e)} {e} {traceback.format_exc()}"
                            )

            work_queue: asyncio.Queue[Job[Subscription]] = asyncio.Queue()
            async with QueuedAsyncPool.managed(
                name="DataLayer subscription update pool",
                worker_async_callable=self.update_subscription,
                job_queue=work_queue,
                target_worker_count=self.subscription_update_concurrency,
                log=self.log,
            ):
                jobs = [Job(input=subscription) for subscription in subscriptions]
                for job in jobs:
                    await work_queue.put(job)

                await asyncio.gather(*(job.done.wait() for job in jobs), return_exceptions=True)

            # Do unsubscribes after the fetching of data is complete, to avoid races.
            async with self.subscription_lock:
                for unsubscribe_data in self.unsubscribe_data_queue:
                    await self.process_unsubscribe(unsubscribe_data.store_id, unsubscribe_data.retain_data)
                self.unsubscribe_data_queue.clear()
            await asyncio.sleep(manage_data_interval)

    async def update_subscription(
        self,
        worker_id: int,
        job: Job[Subscription],
    ) -> None:
        subscription = job.input

        try:
            await self.update_subscriptions_from_wallet(subscription.store_id)
            await self.fetch_and_validate(subscription.store_id)
            await self.upload_files(subscription.store_id)
            await self.clean_old_full_tree_files(subscription.store_id)
        except Exception as e:
            self.log.error(f"Exception while fetching data: {type(e)} {e} {traceback.format_exc()}.")

    async def build_offer_changelist(
        self,
        store_id: bytes32,
        inclusions: Tuple[KeyValue, ...],
    ) -> List[Dict[str, Any]]:
        async with self.data_store.transaction():
            changelist: List[Dict[str, Any]] = []
            for entry in inclusions:
                try:
                    existing_value = await self.get_value(store_id=store_id, key=entry.key)
                except KeyNotFoundError:
                    existing_value = None

                if existing_value == entry.value:
                    # already present, nothing needed
                    continue

                if existing_value is not None:
                    # upsert, delete the existing key and value
                    changelist.append(
                        {
                            "action": "delete",
                            "key": entry.key,
                        }
                    )

                changelist.append(
                    {
                        "action": "insert",
                        "key": entry.key,
                        "value": entry.value,
                    }
                )

            return changelist

    async def process_offered_stores(self, offer_stores: Tuple[OfferStore, ...]) -> Dict[bytes32, StoreProofs]:
        for offer_store in offer_stores:
            await self._update_confirmation_status(store_id=offer_store.store_id)

        async with self.data_store.transaction():
            our_store_proofs: Dict[bytes32, StoreProofs] = {}
            for offer_store in offer_stores:
                changelist = await self.build_offer_changelist(
                    store_id=offer_store.store_id,
                    inclusions=offer_store.inclusions,
                )

                if len(changelist) > 0:
                    new_root_hash = await self.batch_insert(
                        store_id=offer_store.store_id,
                        changelist=changelist,
                        enable_batch_autoinsert=False,
                    )
                else:
                    existing_root = await self.get_root(store_id=offer_store.store_id)
                    if existing_root is None:
                        raise Exception(f"store id not available: {offer_store.store_id.hex()}")
                    new_root_hash = existing_root.root

                if new_root_hash is None:
                    raise Exception("only inserts are supported so a None root hash should not be possible")

                proofs: List[Proof] = []
                for entry in offer_store.inclusions:
                    node_hash = await self.get_key_value_hash(
                        store_id=offer_store.store_id,
                        key=entry.key,
                        root_hash=new_root_hash,
                    )
                    proof_of_inclusion = await self.data_store.get_proof_of_inclusion_by_hash(
                        node_hash=node_hash,
                        store_id=offer_store.store_id,
                        root_hash=new_root_hash,
                    )
                    proof = Proof(
                        key=entry.key,
                        value=entry.value,
                        node_hash=proof_of_inclusion.node_hash,
                        layers=tuple(
                            Layer(
                                other_hash_side=layer.other_hash_side,
                                other_hash=layer.other_hash,
                                combined_hash=layer.combined_hash,
                            )
                            for layer in proof_of_inclusion.layers
                        ),
                    )
                    proofs.append(proof)
                store_proof = StoreProofs(store_id=offer_store.store_id, proofs=tuple(proofs))
                our_store_proofs[offer_store.store_id] = store_proof
            return our_store_proofs

    async def make_offer(
        self,
        maker: Tuple[OfferStore, ...],
        taker: Tuple[OfferStore, ...],
        fee: uint64,
    ) -> Offer:
        async with self.data_store.transaction():
            our_store_proofs = await self.process_offered_stores(offer_stores=maker)

            offer_dict: Dict[Union[uint32, str], int] = {
                **{offer_store.store_id.hex(): -1 for offer_store in maker},
                **{offer_store.store_id.hex(): 1 for offer_store in taker},
            }

            solver: Dict[str, Any] = {
                "0x"
                + our_offer_store.store_id.hex(): {
                    "new_root": "0x" + our_store_proofs[our_offer_store.store_id].proofs[0].root().hex(),
                    "dependencies": [
                        {
                            "launcher_id": "0x" + their_offer_store.store_id.hex(),
                            "values_to_prove": [
                                "0x" + leaf_hash(key=entry.key, value=entry.value).hex()
                                for entry in their_offer_store.inclusions
                            ],
                        }
                        for their_offer_store in taker
                    ],
                }
                for our_offer_store in maker
            }

            res = await self.wallet_rpc.create_offer_for_ids(
                offer_dict=offer_dict,
                solver=solver,
                driver_dict={},
                fee=fee,
                validate_only=False,
                # TODO: probably shouldn't be default but due to peculiarities in the RPC, we're using a stop gap.
                # This is not a change in behavior, the default was already implicit.
                tx_config=DEFAULT_TX_CONFIG,
            )

            offer = Offer(
                trade_id=res.trade_record.trade_id,
                offer=bytes(res.offer),
                taker=taker,
                maker=tuple(our_store_proofs.values()),
            )

            # being extra careful and verifying the offer before returning it
            trading_offer = TradingOffer.from_bytes(offer.offer)
            summary = await DataLayerWallet.get_offer_summary(offer=trading_offer)

            verify_offer(maker=offer.maker, taker=offer.taker, summary=summary)

        await self.data_store.clean_node_table()
        return offer

    async def take_offer(
        self,
        offer_bytes: bytes,
        taker: Tuple[OfferStore, ...],
        maker: Tuple[StoreProofs, ...],
        fee: uint64,
    ) -> TradeRecord:
        async with self.data_store.transaction():
            our_store_proofs = await self.process_offered_stores(offer_stores=taker)

            offer = TradingOffer.from_bytes(offer_bytes)
            summary = await DataLayerWallet.get_offer_summary(offer=offer)

            verify_offer(maker=maker, taker=taker, summary=summary)

            all_store_proofs: Dict[bytes32, StoreProofs] = {
                store_proofs.proofs[0].root(): store_proofs for store_proofs in [*maker, *our_store_proofs.values()]
            }
            proofs_of_inclusion: List[Tuple[str, str, List[str]]] = []
            for root, store_proofs in all_store_proofs.items():
                for proof in store_proofs.proofs:
                    layers = [
                        ProofOfInclusionLayer(
                            combined_hash=layer.combined_hash,
                            other_hash_side=layer.other_hash_side,
                            other_hash=layer.other_hash,
                        )
                        for layer in proof.layers
                    ]
                    proof_of_inclusion = ProofOfInclusion(node_hash=proof.node_hash, layers=layers)
                    sibling_sides_integer = proof_of_inclusion.sibling_sides_integer()
                    proofs_of_inclusion.append(
                        (
                            root.hex(),
                            str(sibling_sides_integer),
                            ["0x" + sibling_hash.hex() for sibling_hash in proof_of_inclusion.sibling_hashes()],
                        )
                    )

            solver: Dict[str, Any] = {
                "proofs_of_inclusion": proofs_of_inclusion,
                **{
                    "0x"
                    + our_offer_store.store_id.hex(): {
                        "new_root": "0x" + root.hex(),
                        "dependencies": [
                            {
                                "launcher_id": "0x" + their_offer_store.store_id.hex(),
                                "values_to_prove": ["0x" + entry.node_hash.hex() for entry in their_offer_store.proofs],
                            }
                            for their_offer_store in maker
                        ],
                    }
                    for our_offer_store in taker
                },
            }

        await self.data_store.clean_node_table()

        # Excluding wallet from transaction since failures in the wallet may occur
        # after the transaction is submitted to the chain.  If we roll back data we
        # may lose published data.

        trade_record = (
            await self.wallet_rpc.take_offer(
                offer=offer,
                solver=solver,
                fee=fee,
                # TODO: probably shouldn't be default but due to peculiarities in the RPC, we're using a stop gap.
                # This is not a change in behavior, the default was already implicit.
                tx_config=DEFAULT_TX_CONFIG,
            )
        ).trade_record

        return trade_record

    async def cancel_offer(self, trade_id: bytes32, secure: bool, fee: uint64) -> None:
        store_ids: List[bytes32] = []

        if not secure:
            trade_record = await self.wallet_rpc.get_offer(trade_id=trade_id, file_contents=True)
            trading_offer = TradingOffer.from_bytes(trade_record.offer)
            summary = await DataLayerWallet.get_offer_summary(offer=trading_offer)
            store_ids = [bytes32.from_hexstr(offered["launcher_id"]) for offered in summary["offered"]]

        await self.wallet_rpc.cancel_offer(
            trade_id=trade_id,
            secure=secure,
            fee=fee,
            # TODO: probably shouldn't be default but due to peculiarities in the RPC, we're using a stop gap.
            # This is not a change in behavior, the default was already implicit.
            tx_config=DEFAULT_TX_CONFIG,
        )

        if not secure:
            for store_id in store_ids:
                await self.data_store.clear_pending_roots(store_id=store_id)

    async def get_sync_status(self, store_id: bytes32) -> SyncStatus:
        await self._update_confirmation_status(store_id=store_id)

        if not await self.data_store.store_id_exists(store_id=store_id):
            raise Exception(f"No store id stored in the local database for {store_id}")
        root = await self.data_store.get_tree_root(store_id=store_id)
        singleton_record = await self.wallet_rpc.dl_latest_singleton(store_id, True)
        if singleton_record is None:
            raise Exception(f"No singleton found for {store_id}")

        return SyncStatus(
            root_hash=self.none_bytes if root.node_hash is None else root.node_hash,
            generation=root.generation,
            target_root_hash=singleton_record.root,
            target_generation=singleton_record.generation,
        )

    async def get_uploaders(self, store_id: bytes32) -> List[PluginRemote]:
        uploaders = []
        for uploader in self.uploaders:
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(
                        uploader.url + "/handle_upload",
                        json={"store_id": store_id.hex()},
                        headers=uploader.headers,
                    ) as response:
                        res_json = await response.json()
                        if res_json["handle_upload"]:
                            uploaders.append(uploader)
                except Exception as e:
                    self.log.error(f"get_uploader could not get response {e}")
        return uploaders

    async def check_plugins(self) -> PluginStatus:
        coros = [get_plugin_info(plugin_remote=plugin) for plugin in {*self.uploaders, *self.downloaders}]
        results = dict(await asyncio.gather(*coros))

        unknown = {
            "name": "unknown",
            "version": "unknown",
            "instance": "unknown",
        }

        uploader_status = {uploader.url: results.get(uploader, unknown) for uploader in self.uploaders}
        downloader_status = {downloader.url: results.get(downloader, unknown) for downloader in self.downloaders}

        return PluginStatus(uploaders=uploader_status, downloaders=downloader_status)
