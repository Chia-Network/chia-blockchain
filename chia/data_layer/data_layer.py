import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Awaitable, Set
import aiosqlite
import time
import traceback
import asyncio
import aiohttp
from chia.data_layer.data_layer_util import InternalNode, TerminalNode, Subscription, DiffData, Status, Root
from chia.data_layer.data_store import DataStore
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.server import ChiaServer
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import load_config
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32, uint64
from chia.util.path import path_from_root
from chia.wallet.transaction_record import TransactionRecord
from chia.data_layer.data_layer_wallet import SingletonRecord
from chia.data_layer.download_data import insert_from_delta_file, write_files_for_root
from chia.data_layer.data_layer_server import DataLayerServer


class DataLayer:
    data_store: DataStore
    data_layer_server: DataLayerServer
    db_wrapper: DBWrapper
    batch_update_db_wrapper: DBWrapper
    db_path: Path
    connection: Optional[aiosqlite.Connection]
    config: Dict[str, Any]
    log: logging.Logger
    wallet_rpc_init: Awaitable[WalletRpcClient]
    state_changed_callback: Optional[Callable[..., object]]
    wallet_id: uint64
    initialized: bool
    none_bytes: bytes32
    lock: asyncio.Lock

    def __init__(
        self,
        root_path: Path,
        wallet_rpc_init: Awaitable[WalletRpcClient],
        name: Optional[str] = None,
    ):
        if name == "":
            # TODO: If no code depends on "" counting as 'unspecified' then we do not
            #       need this.
            name = None
        config = load_config(root_path, "config.yaml", "data_layer")
        self.initialized = False
        self.config = config
        self.connection = None
        self.wallet_rpc_init = wallet_rpc_init
        self.log = logging.getLogger(name if name is None else __name__)
        self._shut_down: bool = False
        db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])
        self.db_path = path_from_root(root_path, db_path_replaced)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        server_files_replaced: str = config.get(
            "server_files_location", "data_layer/db/server_files_location_CHALLENGE"
        ).replace("CHALLENGE", config["selected_network"])
        self.server_files_location = path_from_root(root_path, server_files_replaced)
        self.server_files_location.mkdir(parents=True, exist_ok=True)
        self.data_layer_server = DataLayerServer(root_path, self.config, self.log)
        self.none_bytes = bytes32([0] * 32)
        self.lock = asyncio.Lock()

    def _set_state_changed_callback(self, callback: Callable[..., object]) -> None:
        self.state_changed_callback = callback

    def set_server(self, server: ChiaServer) -> None:
        self.server = server

    async def _start(self) -> bool:
        self.connection = await aiosqlite.connect(self.db_path)
        self.db_wrapper = DBWrapper(self.connection)
        self.data_store = await DataStore.create(self.db_wrapper)
        self.wallet_rpc = await self.wallet_rpc_init
        self.subscription_lock: asyncio.Lock = asyncio.Lock()
        if self.config.get("run_server", False):
            await self.data_layer_server.start()

        self.periodically_manage_data_task: asyncio.Task[Any] = asyncio.create_task(self.periodically_manage_data())
        return True

    def _close(self) -> None:
        # TODO: review for anything else we need to do here
        self._shut_down = True

    async def _await_closed(self) -> None:
        if self.connection is not None:
            await self.connection.close()
        if self.config.get("run_server", False):
            await self.data_layer_server.stop()
        try:
            self.periodically_manage_data_task.cancel()
        except asyncio.CancelledError:
            pass

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
        batch_hash = await self.data_store.insert_batch(tree_id, changelist, lock=True)
        t2 = time.monotonic()
        self.log.info(f"Data store batch update process time: {t2 - t1}.")
        # todo return empty node hash from get_tree_root
        if batch_hash is not None:
            node_hash = batch_hash
        else:
            node_hash = self.none_bytes  # todo change

        transaction_record = await self.wallet_rpc.dl_update_root(tree_id, node_hash, fee)
        return transaction_record

    async def get_value(self, store_id: bytes32, key: bytes) -> Optional[bytes]:
        async with self.lock:
            await self._update_confirmation_status(tree_id=store_id)
        res = await self.data_store.get_node_by_key(tree_id=store_id, key=key)
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

    async def fetch_and_validate(self, subscription: Subscription) -> None:
        tree_id = subscription.tree_id
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
            await self.data_store.create_tree(tree_id=tree_id)

        for url in subscription.urls:
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
                f"Downloading files {subscription.tree_id}. "
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
                success = await insert_from_delta_file(
                    self.data_store,
                    subscription.tree_id,
                    root.generation,
                    [record.root for record in reversed(to_download)],
                    url,
                    self.server_files_location,
                    self.log,
                )
                if success:
                    self.log.info(
                        f"Finished downloading and validating {subscription.tree_id}. "
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

    async def upload_files(self, tree_id: bytes32) -> None:
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
        while publish_generation > 0 and await write_files_for_root(
            self.data_store,
            tree_id,
            root,
            self.server_files_location,
        ):
            publish_generation -= 1
            root = await self.data_store.get_tree_root(tree_id=tree_id, generation=publish_generation)

    async def add_missing_files(self, store_id: bytes32, override: bool, foldername: Optional[Path]) -> None:
        root = await self.data_store.get_tree_root(tree_id=store_id)
        singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(store_id, True)
        if singleton_record is None:
            self.log.error(f"No singleton record found for: {store_id}")
            return
        max_generation = min(singleton_record.generation, 0 if root is None else root.generation)
        server_files_location = foldername if foldername is not None else self.server_files_location
        for generation in range(1, max_generation + 1):
            root = await self.data_store.get_tree_root(tree_id=store_id, generation=generation)
            await write_files_for_root(self.data_store, store_id, root, server_files_location, override)

    async def subscribe(self, store_id: bytes32, urls: List[str]) -> None:
        parsed_urls = [url.rstrip("/") for url in urls]
        subscription = Subscription(store_id, parsed_urls)
        subscriptions = await self.get_subscriptions()
        if subscription.tree_id in (subscription.tree_id for subscription in subscriptions):
            await self.data_store.update_existing_subscription(subscription)
            self.log.info(f"Successfully updated subscription {subscription.tree_id}")
            return
        await self.wallet_rpc.dl_track_new(subscription.tree_id)
        async with self.subscription_lock:
            await self.data_store.subscribe(subscription)
        self.log.info(f"Subscribed to {subscription.tree_id}")

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
                        await self.fetch_and_validate(subscription)
                        await self.upload_files(subscription.tree_id)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        self.log.error(f"Exception while fetching data: {type(e)} {e} {traceback.format_exc()}.")
            try:
                await asyncio.sleep(manage_data_interval)
            except asyncio.CancelledError:
                raise
