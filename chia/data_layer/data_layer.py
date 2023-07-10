from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
import traceback
from pathlib import Path
from typing import Any, Awaitable, Dict, List, Optional, Set, Tuple, Union

import aiohttp

from chia.data_layer.data_layer_errors import KeyNotFoundError
from chia.data_layer.data_layer_util import (
    DiffData,
    InternalNode,
    KeyValue,
    Layer,
    Offer,
    OfferStore,
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
    leaf_hash,
)
from chia.data_layer.data_layer_wallet import DataLayerWallet, Mirror, SingletonRecord, verify_offer
from chia.data_layer.data_store import DataStore
from chia.data_layer.download_data import insert_from_delta_file, write_files_for_root
from chia.rpc.rpc_server import StateChangedProtocol, default_get_connections
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.util.path import path_from_root
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer as TradingOffer
from chia.wallet.transaction_record import TransactionRecord


async def get_plugin_info(url: str) -> Tuple[str, Dict[str, Any]]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url + "/plugin_info", json={}) as response:
                ret = {"status": response.status}
                if response.status == 200:
                    ret["response"] = json.loads(await response.text())
                return url, ret
    except aiohttp.ClientError as e:
        return url, {"error": f"ClientError: {e}"}


class DataLayer:
    data_store: DataStore
    db_path: Path
    config: Dict[str, Any]
    root_path: Path
    log: logging.Logger
    wallet_rpc_init: Awaitable[WalletRpcClient]
    state_changed_callback: Optional[StateChangedProtocol] = None
    wallet_id: uint64
    initialized: bool
    none_bytes: bytes32
    lock: asyncio.Lock
    _server: Optional[ChiaServer]
    downloaders: List[str]
    uploaders: List[str]

    @property
    def server(self) -> ChiaServer:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._server is None:
            raise RuntimeError("server not assigned")

        return self._server

    def __init__(
        self,
        config: Dict[str, Any],
        root_path: Path,
        wallet_rpc_init: Awaitable[WalletRpcClient],
        downloaders: List[str],
        uploaders: List[str],  # dont add FilesystemUploader to this, it is the default uploader
        name: Optional[str] = None,
    ):
        if name == "":
            # TODO: If no code depends on "" counting as 'unspecified' then we do not
            #       need this.
            name = None
        self.initialized = False
        self.config = config
        self.root_path = root_path
        self.connection = None
        self.wallet_rpc_init = wallet_rpc_init
        self.log = logging.getLogger(name if name is None else __name__)
        self._shut_down: bool = False
        db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])
        self.db_path = path_from_root(self.root_path, db_path_replaced)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        server_files_replaced: str = config.get(
            "server_files_location", "data_layer/db/server_files_location_CHALLENGE"
        ).replace("CHALLENGE", config["selected_network"])
        self.server_files_location = path_from_root(self.root_path, server_files_replaced)
        self.server_files_location.mkdir(parents=True, exist_ok=True)
        self.none_bytes = bytes32([0] * 32)
        self.lock = asyncio.Lock()
        self._server = None
        self.downloaders = downloaders
        self.uploaders = uploaders

    def _set_state_changed_callback(self, callback: StateChangedProtocol) -> None:
        self.state_changed_callback = callback

    async def on_connect(self, connection: WSChiaConnection) -> None:
        pass

    def get_connections(self, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

    def set_server(self, server: ChiaServer) -> None:
        self._server = server

    async def _start(self) -> None:
        sql_log_path: Optional[Path] = None
        if self.config.get("log_sqlite_cmds", False):
            sql_log_path = path_from_root(self.root_path, "log/data_sql.log")
            self.log.info(f"logging SQL commands to {sql_log_path}")

        self.data_store = await DataStore.create(database=self.db_path, sql_log_path=sql_log_path)
        self.wallet_rpc = await self.wallet_rpc_init
        self.subscription_lock: asyncio.Lock = asyncio.Lock()

        self.periodically_manage_data_task: asyncio.Task[Any] = asyncio.create_task(self.periodically_manage_data())

    def _close(self) -> None:
        # TODO: review for anything else we need to do here
        self._shut_down = True
        self.wallet_rpc.close()

    async def _await_closed(self) -> None:
        if self.connection is not None:
            await self.connection.close()
        try:
            self.periodically_manage_data_task.cancel()
        except asyncio.CancelledError:
            pass
        await self.data_store.close()
        await self.wallet_rpc.await_closed()

    async def create_store(
        self, fee: uint64, root: bytes32 = bytes32([0] * 32)
    ) -> Tuple[List[TransactionRecord], bytes32]:
        txs, tree_id = await self.wallet_rpc.create_new_dl(root, fee)
        res = await self.data_store.create_tree(tree_id=tree_id)
        if res is None:
            self.log.fatal("failed creating store")
        self.initialized = True
        return txs, tree_id

    async def batch_update(
        self,
        tree_id: bytes32,
        changelist: List[Dict[str, Any]],
        fee: uint64,
    ) -> TransactionRecord:
        await self.batch_insert(tree_id=tree_id, changelist=changelist)
        return await self.publish_update(tree_id=tree_id, fee=fee)

    async def batch_insert(
        self,
        tree_id: bytes32,
        changelist: List[Dict[str, Any]],
    ) -> bytes32:
        async with self.data_store.transaction():
            # Make sure we update based on the latest confirmed root.
            async with self.lock:
                await self._update_confirmation_status(tree_id=tree_id)
            pending_root: Optional[Root] = await self.data_store.get_pending_root(tree_id=tree_id)
            if pending_root is not None:
                raise Exception("Already have a pending root waiting for confirmation.")

            # check before any DL changes that this singleton is currently owned by this wallet
            singleton_records: List[SingletonRecord] = await self.get_owned_stores()
            if not any(tree_id == singleton.launcher_id for singleton in singleton_records):
                raise ValueError(f"Singleton with launcher ID {tree_id} is not owned by DL Wallet")

            t1 = time.monotonic()
            batch_hash = await self.data_store.insert_batch(tree_id, changelist)
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
        tree_id: bytes32,
        fee: uint64,
    ) -> TransactionRecord:
        # Make sure we update based on the latest confirmed root.
        async with self.lock:
            await self._update_confirmation_status(tree_id=tree_id)
        pending_root: Optional[Root] = await self.data_store.get_pending_root(tree_id=tree_id)
        if pending_root is None:
            raise Exception("Latest root is already confirmed.")

        root_hash = self.none_bytes if pending_root.node_hash is None else pending_root.node_hash

        transaction_record = await self.wallet_rpc.dl_update_root(
            launcher_id=tree_id,
            new_root=root_hash,
            fee=fee,
        )
        return transaction_record

    async def get_key_value_hash(
        self,
        store_id: bytes32,
        key: bytes,
        root_hash: Optional[bytes32] = None,
    ) -> bytes32:
        async with self.data_store.transaction():
            async with self.lock:
                await self._update_confirmation_status(tree_id=store_id)
            node = await self.data_store.get_node_by_key(tree_id=store_id, key=key, root_hash=root_hash)
            return node.hash

    async def get_value(self, store_id: bytes32, key: bytes, root_hash: Optional[bytes32] = None) -> Optional[bytes]:
        async with self.data_store.transaction():
            async with self.lock:
                await self._update_confirmation_status(tree_id=store_id)
            res = await self.data_store.get_node_by_key(tree_id=store_id, key=key, root_hash=root_hash)
            if res is None:
                self.log.error("Failed to fetch key")
                return None
            return res.value

    async def get_keys_values(self, store_id: bytes32, root_hash: Optional[bytes32]) -> List[TerminalNode]:
        async with self.lock:
            await self._update_confirmation_status(tree_id=store_id)
        res = await self.data_store.get_keys_values(store_id, root_hash)
        if res is None:
            self.log.error("Failed to fetch keys values")
        return res

    async def get_keys(self, store_id: bytes32, root_hash: Optional[bytes32]) -> List[bytes]:
        async with self.lock:
            await self._update_confirmation_status(tree_id=store_id)
        res = await self.data_store.get_keys(store_id, root_hash)
        return res

    async def get_ancestors(self, node_hash: bytes32, store_id: bytes32) -> List[InternalNode]:
        async with self.lock:
            await self._update_confirmation_status(tree_id=store_id)

        res = await self.data_store.get_ancestors(node_hash=node_hash, tree_id=store_id)
        if res is None:
            self.log.error("Failed to get ancestors")
        return res

    async def get_root(self, store_id: bytes32) -> Optional[SingletonRecord]:
        latest = await self.wallet_rpc.dl_latest_singleton(store_id, True)
        if latest is None:
            self.log.error(f"Failed to get root for {store_id.hex()}")
        return latest

    async def get_local_root(self, store_id: bytes32) -> Optional[bytes32]:
        async with self.lock:
            await self._update_confirmation_status(tree_id=store_id)

        res = await self.data_store.get_tree_root(tree_id=store_id)
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

    async def _update_confirmation_status(self, tree_id: bytes32) -> None:
        async with self.data_store.transaction():
            try:
                root = await self.data_store.get_tree_root(tree_id=tree_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                root = None
            singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(tree_id, True)
            if singleton_record is None:
                return
            if root is None:
                pending_root = await self.data_store.get_pending_root(tree_id=tree_id)
                if pending_root is not None:
                    if pending_root.generation == 0 and pending_root.node_hash is None:
                        await self.data_store.change_root_status(pending_root, Status.COMMITTED)
                        await self.data_store.clear_pending_roots(tree_id=tree_id)
                        return
                    else:
                        root = None
            if root is None:
                self.log.info(f"Don't have pending root for {tree_id}.")
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
                launcher_id=tree_id,
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
                await self.data_store.clear_pending_roots(tree_id=tree_id)
                await self.data_store.shift_root_generations(tree_id=tree_id, shift_size=generation_shift)
            else:
                expected_root_hash = None if new_hashes[0] == self.none_bytes else new_hashes[0]
                pending_root = await self.data_store.get_pending_root(tree_id=tree_id)
                if (
                    pending_root is not None
                    and pending_root.generation == root.generation + 1
                    and pending_root.node_hash == expected_root_hash
                ):
                    await self.data_store.change_root_status(pending_root, Status.COMMITTED)
                    await self.data_store.build_ancestor_table_for_latest_root(tree_id=tree_id)
            await self.data_store.clear_pending_roots(tree_id=tree_id)

    async def fetch_and_validate(self, tree_id: bytes32) -> None:
        singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(tree_id, True)
        if singleton_record is None:
            self.log.info(f"Fetch data: No singleton record for {tree_id}.")
            return
        if singleton_record.generation == uint32(0):
            self.log.info(f"Fetch data: No data on chain for {tree_id}.")
            return

        async with self.lock:
            await self._update_confirmation_status(tree_id=tree_id)

        if not await self.data_store.tree_id_exists(tree_id=tree_id):
            await self.data_store.create_tree(tree_id=tree_id, status=Status.COMMITTED)

        timestamp = int(time.time())
        servers_info = await self.data_store.get_available_servers_for_store(tree_id, timestamp)
        # TODO: maybe append a random object to the whole DataLayer class?
        random.shuffle(servers_info)
        for server_info in servers_info:
            url = server_info.url

            root = await self.data_store.get_tree_root(tree_id=tree_id)
            if root.generation > singleton_record.generation:
                self.log.info(
                    "Fetch data: local DL store is ahead of chain generation. "
                    f"Local root: {root}. Singleton: {singleton_record}"
                )
                break
            if root.generation == singleton_record.generation:
                self.log.info(f"Fetch data: wallet generation matching on-chain generation: {tree_id}.")
                break

            self.log.info(
                f"Downloading files {tree_id}. "
                f"Current wallet generation: {root.generation}. "
                f"Target wallet generation: {singleton_record.generation}. "
                f"Server used: {url}."
            )

            to_download = await self.wallet_rpc.dl_history(
                launcher_id=tree_id,
                min_generation=uint32(root.generation + 1),
                max_generation=singleton_record.generation,
            )
            try:
                timeout = self.config.get("client_timeout", 15)
                proxy_url = self.config.get("proxy_url", None)
                success = await insert_from_delta_file(
                    self.data_store,
                    tree_id,
                    root.generation,
                    [record.root for record in reversed(to_download)],
                    server_info,
                    self.server_files_location,
                    timeout,
                    self.log,
                    proxy_url,
                    await self.get_downloader(tree_id, url),
                )
                if success:
                    self.log.info(
                        f"Finished downloading and validating {tree_id}. "
                        f"Wallet generation saved: {singleton_record.generation}. "
                        f"Root hash saved: {singleton_record.root}."
                    )
                    break
            except asyncio.CancelledError:
                raise
            except aiohttp.client_exceptions.ClientConnectorError:
                self.log.warning(f"Server {url} unavailable for {tree_id}.")
            except Exception as e:
                self.log.warning(f"Exception while downloading files for {tree_id}: {e} {traceback.format_exc()}.")

    async def get_downloader(self, tree_id: bytes32, url: str) -> Optional[str]:
        request_json = {"store_id": tree_id.hex(), "url": url}
        for d in self.downloaders:
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(d + "/handle_download", json=request_json) as response:
                        res_json = await response.json()
                        if res_json["handle_download"]:
                            return d
                except Exception as e:
                    self.log.error(f"get_downloader could not get response: {type(e).__name__}: {e}")
        return None

    async def upload_files(self, tree_id: bytes32) -> None:
        uploaders = await self.get_uploaders(tree_id)
        singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(tree_id, True)
        if singleton_record is None:
            self.log.info(f"Upload files: no on-chain record for {tree_id}.")
            return
        async with self.lock:
            await self._update_confirmation_status(tree_id=tree_id)

        root = await self.data_store.get_tree_root(tree_id=tree_id)
        publish_generation = min(singleton_record.generation, 0 if root is None else root.generation)
        # If we make some batch updates, which get confirmed to the chain, we need to create the files.
        # We iterate back and write the missing files, until we find the files already written.
        root = await self.data_store.get_tree_root(tree_id=tree_id, generation=publish_generation)
        while publish_generation > 0:
            write_file_result = await write_files_for_root(self.data_store, tree_id, root, self.server_files_location)
            if not write_file_result.result:
                # this particular return only happens if the files already exist, no need to log anything
                break
            try:
                if uploaders is not None and len(uploaders) > 0:
                    request_json = {
                        "store_id": tree_id.hex(),
                        "full_tree_filename": write_file_result.full_tree.name,
                        "diff_filename": write_file_result.diff_tree.name,
                    }
                    for uploader in uploaders:
                        self.log.info(f"Using uploader {uploader} for store {tree_id.hex()}")
                        async with aiohttp.ClientSession() as session:
                            async with session.post(uploader + "/upload", json=request_json) as response:
                                res_json = await response.json()
                                if res_json["uploaded"]:
                                    self.log.info(
                                        f"Uploaded files to {uploader} for store {tree_id.hex()} "
                                        "generation {publish_generation}"
                                    )
                                else:
                                    self.log.error(
                                        f"Failed to upload files to, will retry later: {uploader} : {res_json}"
                                    )
            except Exception as e:
                self.log.error(f"Exception uploading files, will retry later: tree id {tree_id}")
                self.log.debug(f"Failed to upload files, cleaning local files: {type(e).__name__}: {e}")
                os.remove(write_file_result.full_tree)
                os.remove(write_file_result.diff_tree)
            publish_generation -= 1
            root = await self.data_store.get_tree_root(tree_id=tree_id, generation=publish_generation)

    async def add_missing_files(self, store_id: bytes32, overwrite: bool, foldername: Optional[Path]) -> None:
        root = await self.data_store.get_tree_root(tree_id=store_id)
        singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(store_id, True)
        if singleton_record is None:
            self.log.error(f"No singleton record found for: {store_id}")
            return
        max_generation = min(singleton_record.generation, 0 if root is None else root.generation)
        server_files_location = foldername if foldername is not None else self.server_files_location
        files = []
        for generation in range(1, max_generation + 1):
            root = await self.data_store.get_tree_root(tree_id=store_id, generation=generation)
            res = await write_files_for_root(self.data_store, store_id, root, server_files_location, overwrite)
            files.append(res.diff_tree.name)
            files.append(res.full_tree.name)

        uploaders = await self.get_uploaders(store_id)
        if uploaders is not None and len(uploaders) > 0:
            request_json = {"store_id": store_id.hex(), "files": json.dumps(files)}
            for uploader in uploaders:
                async with aiohttp.ClientSession() as session:
                    async with session.post(uploader + "/add_missing_files", json=request_json) as response:
                        res_json = await response.json()
                        if not res_json["uploaded"]:
                            self.log.error(f"failed to upload to uploader {uploader}")
                        else:
                            self.log.debug(f"uploaded to uploader {uploader}")

    async def subscribe(self, store_id: bytes32, urls: List[str]) -> None:
        parsed_urls = [url.rstrip("/") for url in urls]
        subscription = Subscription(store_id, [ServerInfo(url, 0, 0) for url in parsed_urls])
        await self.wallet_rpc.dl_track_new(subscription.tree_id)
        async with self.subscription_lock:
            await self.data_store.subscribe(subscription)
        self.log.info(f"Done adding subscription: {subscription.tree_id}")

    async def remove_subscriptions(self, store_id: bytes32, urls: List[str]) -> None:
        parsed_urls = [url.rstrip("/") for url in urls]
        async with self.subscription_lock:
            await self.data_store.remove_subscriptions(store_id, parsed_urls)

    async def unsubscribe(self, tree_id: bytes32) -> None:
        subscriptions = await self.get_subscriptions()
        if tree_id not in (subscription.tree_id for subscription in subscriptions):
            raise RuntimeError("No subscription found for the given tree_id.")
        async with self.subscription_lock:
            await self.data_store.unsubscribe(tree_id)
        await self.wallet_rpc.dl_stop_tracking(tree_id)
        self.log.info(f"Unsubscribed to {tree_id}")

    async def get_subscriptions(self) -> List[Subscription]:
        async with self.subscription_lock:
            return await self.data_store.get_subscriptions()

    async def add_mirror(self, store_id: bytes32, urls: List[str], amount: uint64, fee: uint64) -> None:
        bytes_urls = [bytes(url, "utf8") for url in urls]
        await self.wallet_rpc.dl_new_mirror(store_id, amount, bytes_urls, fee)

    async def delete_mirror(self, coin_id: bytes32, fee: uint64) -> None:
        await self.wallet_rpc.dl_delete_mirror(coin_id, fee)

    async def get_mirrors(self, tree_id: bytes32) -> List[Mirror]:
        return await self.wallet_rpc.dl_get_mirrors(tree_id)

    async def update_subscriptions_from_wallet(self, tree_id: bytes32) -> None:
        mirrors: List[Mirror] = await self.wallet_rpc.dl_get_mirrors(tree_id)
        urls: List[str] = []
        for mirror in mirrors:
            urls = urls + [url.decode("utf8") for url in mirror.urls]
        urls = [url.rstrip("/") for url in urls]
        await self.data_store.update_subscriptions_from_wallet(tree_id, urls)

    async def get_owned_stores(self) -> List[SingletonRecord]:
        return await self.wallet_rpc.dl_owned_singletons()

    async def get_kv_diff(self, tree_id: bytes32, hash_1: bytes32, hash_2: bytes32) -> Set[DiffData]:
        return await self.data_store.get_kv_diff(tree_id, hash_1, hash_2)

    async def periodically_manage_data(self) -> None:
        manage_data_interval = self.config.get("manage_data_interval", 60)
        while not self._shut_down:
            async with self.subscription_lock:
                try:
                    subscriptions = await self.data_store.get_subscriptions()
                    for subscription in subscriptions:
                        await self.wallet_rpc.dl_track_new(subscription.tree_id)
                    break
                except aiohttp.client_exceptions.ClientConnectorError:
                    pass
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.log.error(f"Exception while requesting wallet track subscription: {type(e)} {e}")

            self.log.warning("Cannot connect to the wallet. Retrying in 3s.")

            delay_until = time.monotonic() + 3
            while time.monotonic() < delay_until:
                if self._shut_down:
                    break
                try:
                    await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    raise

        while not self._shut_down:
            async with self.subscription_lock:
                subscriptions = await self.data_store.get_subscriptions()

            # Subscribe to all local tree_ids that we can find on chain.
            local_tree_ids = await self.data_store.get_tree_ids()
            subscription_tree_ids = set(subscription.tree_id for subscription in subscriptions)
            for local_id in local_tree_ids:
                if local_id not in subscription_tree_ids:
                    try:
                        await self.subscribe(local_id, [])
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        self.log.info(
                            f"Can't subscribe to locally stored {local_id}: {type(e)} {e} {traceback.format_exc()}"
                        )

            async with self.subscription_lock:
                for subscription in subscriptions:
                    try:
                        await self.update_subscriptions_from_wallet(subscription.tree_id)
                        await self.fetch_and_validate(subscription.tree_id)
                        await self.upload_files(subscription.tree_id)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        self.log.error(f"Exception while fetching data: {type(e)} {e} {traceback.format_exc()}.")
            try:
                await asyncio.sleep(manage_data_interval)
            except asyncio.CancelledError:
                raise

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
        async with self.data_store.transaction():
            our_store_proofs: Dict[bytes32, StoreProofs] = {}
            for offer_store in offer_stores:
                async with self.lock:
                    await self._update_confirmation_status(tree_id=offer_store.store_id)

                changelist = await self.build_offer_changelist(
                    store_id=offer_store.store_id,
                    inclusions=offer_store.inclusions,
                )

                if len(changelist) > 0:
                    new_root_hash = await self.batch_insert(
                        tree_id=offer_store.store_id,
                        changelist=changelist,
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
                        tree_id=offer_store.store_id,
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

            wallet_offer, trade_record = await self.wallet_rpc.create_offer_for_ids(
                offer_dict=offer_dict,
                solver=solver,
                driver_dict={},
                fee=fee,
                validate_only=False,
            )
            if wallet_offer is None:
                raise Exception("offer is None despite validate_only=False")

            offer = Offer(
                trade_id=trade_record.trade_id,
                offer=bytes(wallet_offer),
                taker=taker,
                maker=tuple(our_store_proofs.values()),
            )

            # being extra careful and verifying the offer before returning it
            trading_offer = TradingOffer.from_bytes(offer.offer)
            summary = await DataLayerWallet.get_offer_summary(offer=trading_offer)

            verify_offer(maker=offer.maker, taker=offer.taker, summary=summary)

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

        # Excluding wallet from transaction since failures in the wallet may occur
        # after the transaction is submitted to the chain.  If we roll back data we
        # may lose published data.

        trade_record = await self.wallet_rpc.take_offer(
            offer=offer,
            solver=solver,
            fee=fee,
        )

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
        )

        if not secure:
            for store_id in store_ids:
                await self.data_store.clear_pending_roots(tree_id=store_id)

    async def get_sync_status(self, store_id: bytes32) -> SyncStatus:
        async with self.lock:
            await self._update_confirmation_status(tree_id=store_id)

        if not await self.data_store.tree_id_exists(tree_id=store_id):
            raise Exception(f"No tree id stored in the local database for {store_id}")
        root = await self.data_store.get_tree_root(tree_id=store_id)
        singleton_record = await self.wallet_rpc.dl_latest_singleton(store_id, True)
        if singleton_record is None:
            raise Exception(f"No singleton found for {store_id}")

        return SyncStatus(
            root_hash=self.none_bytes if root.node_hash is None else root.node_hash,
            generation=root.generation,
            target_root_hash=singleton_record.root,
            target_generation=singleton_record.generation,
        )

    async def get_uploaders(self, tree_id: bytes32) -> List[str]:
        uploaders = []
        for uploader in self.uploaders:
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(uploader + "/handle_upload", json={"store_id": tree_id.hex()}) as response:
                        res_json = await response.json()
                        if res_json["handle_upload"]:
                            uploaders.append(uploader)
                except Exception as e:
                    self.log.error(f"get_uploader could not get response {e}")
        return uploaders

    async def check_plugins(self) -> PluginStatus:
        coros = [get_plugin_info(url=plugin) for plugin in {*self.uploaders, *self.downloaders}]
        results = dict(await asyncio.gather(*coros))

        uploader_status = {url: results.get(url, "unknown") for url in self.uploaders}
        downloader_status = {url: results.get(url, "unknown") for url in self.downloaders}

        return PluginStatus(uploaders=uploader_status, downloaders=downloader_status)
