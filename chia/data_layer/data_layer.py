import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Awaitable, Set
import aiosqlite
import traceback
import asyncio
import aiohttp
from chia.data_layer.data_layer_types import InternalNode, TerminalNode, DownloadMode, Subscription, Root, DiffData
from chia.data_layer.data_store import DataStore
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.server import ChiaServer
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import load_config
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32, uint64, uint16
from chia.util.path import mkdir, path_from_root
from chia.wallet.transaction_record import TransactionRecord
from chia.data_layer.data_layer_wallet import SingletonRecord
from chia.data_layer.download_data import download_data
from chia.data_layer.data_layer_server import DataLayerServer


class DataLayer:
    data_store: DataStore
    data_layer_server: DataLayerServer
    db_wrapper: DBWrapper
    db_path: Path
    connection: Optional[aiosqlite.Connection]
    config: Dict[str, Any]
    log: logging.Logger
    wallet_rpc_init: Awaitable[WalletRpcClient]
    state_changed_callback: Optional[Callable[..., object]]
    wallet_id: uint64
    initialized: bool
    none_bytes: bytes32

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
        mkdir(self.db_path.parent)
        self.data_layer_server = DataLayerServer(self.config, self.db_path, self.log)
        self.none_bytes = bytes32([0] * 32)

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
        subscriptions = await self.get_subscriptions()
        for subscription in subscriptions:
            await self.wallet_rpc.dl_track_new(subscription.tree_id)
        self.periodically_fetch_data_task: asyncio.Task[Any] = asyncio.create_task(self.periodically_fetch_data())
        return True

    def _close(self) -> None:
        # TODO: review for anything else we need to do here
        self._shut_down = True

    async def _await_closed(self) -> None:
        if self.connection is not None:
            await self.connection.close()
        if self.config.get("run_server", False):
            await self.data_layer_server.stop()
        self.periodically_fetch_data_task.cancel()

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
        hint_keys_values = await self.data_store.get_keys_values_dict(tree_id)
        for change in changelist:
            if change["action"] == "insert":
                key = change["key"]
                value = change["value"]
                reference_node_hash = change.get("reference_node_hash")
                side = change.get("side")
                if reference_node_hash or side:
                    await self.data_store.insert(key, value, tree_id, reference_node_hash, side, hint_keys_values)
                await self.data_store.autoinsert(key, value, tree_id, hint_keys_values)
            else:
                assert change["action"] == "delete"
                key = change["key"]
                await self.data_store.delete(key, tree_id, hint_keys_values)

        root = await self.data_store.get_tree_root(tree_id)
        # todo return empty node hash from get_tree_root
        if root.node_hash is not None:
            node_hash = root.node_hash
        else:
            node_hash = self.none_bytes  # todo change

        # todo do we need a lock here ?
        transaction_record = await self.wallet_rpc.dl_update_root(tree_id, node_hash, fee)
        new_root_wallet = await self.wallet_rpc.dl_latest_singleton(tree_id)
        assert new_root_wallet
        await self.data_store.increment_submissions(tree_id, root.generation)
        if node_hash != new_root_wallet.root:
            raise Exception("local root does not match wallet")
        assert transaction_record
        # todo register callback to change status in data store
        # await self.data_store.change_root_status(root, Status.COMMITTED)
        return transaction_record

    async def get_value(self, store_id: bytes32, key: bytes) -> Optional[bytes]:
        res = await self.data_store.get_node_by_key(tree_id=store_id, key=key)
        if res is None:
            self.log.error("Failed to fetch key")
            return None
        return res.value

    async def get_keys_values(self, store_id: bytes32, root_hash: Optional[bytes32]) -> List[TerminalNode]:
        res = await self.data_store.get_keys_values(store_id, root_hash)
        if res is None:
            self.log.error("Failed to fetch keys values")
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

    async def get_local_root(self, store_id: bytes32) -> Optional[Root]:
        res = await self.data_store.get_tree_root(tree_id=store_id)
        if res is None:
            self.log.error(f"Failed to get root for {store_id.hex()}")
        return res

    async def resubmit_root(self, store_id: bytes32, fee: uint64) -> TransactionRecord:
        root = await self.data_store.get_tree_root(tree_id=store_id)
        assert root.node_hash
        root_wallet = await self.wallet_rpc.dl_latest_singleton(store_id)
        assert root_wallet
        if root.node_hash == root_wallet.root:
            raise Exception("local root matches wallet root")
        await self.data_store.increment_submissions(store_id, root.generation)
        return await self.wallet_rpc.dl_update_root(store_id, root.node_hash, fee)

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

    async def _validate_batch(
        self,
        tree_id: bytes32,
        to_check: List[SingletonRecord],
        min_generation: int,
    ) -> bool:
        root: Optional[Root] = await self.data_store.get_tree_root(tree_id=tree_id)
        assert root is not None
        if to_check[0].root == (root.node_hash if root.node_hash is not None else self.none_bytes):
            self.log.info(
                f"Validated chain hash {to_check[0].root} in downloaded datastore. "
                f"Wallet generation: {to_check[0].generation}"
            )
        else:
            return False

        max_generation = root.generation
        last_checked_hash = to_check[0].root
        to_check.pop(0)

        for record in to_check:
            # Ignore two consecutive identical root hashes, as we've already validated it.
            if record.root == last_checked_hash:
                self.log.info(f"Skipped checking {record.root}, as it matches the previously checked hash.")
                continue
            # Pick the latest root in our data store with the desired hash, before our already validated data.
            root = await self.data_store.get_last_tree_root_by_hash(
                tree_id, None if record.root == self.none_bytes else record.root, max_generation
            )
            if root is None or root.generation < min_generation:
                return False

            self.log.info(
                f"Validated chain hash {record.root} in downloaded datastore. "
                f"Wallet generation: {record.generation}"
            )
            max_generation = root.generation
            last_checked_hash = record.root

        return True

    async def fetch_and_validate(self, subscription: Subscription) -> None:
        tree_id = subscription.tree_id
        singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(tree_id, True)
        if singleton_record is None:
            self.log.info(f"Fetch data: No singleton record for {tree_id}.")
            return
        if singleton_record.generation == uint32(0):
            self.log.info(f"Fetch data: No data on chain for {tree_id}.")
            return
        old_root: Optional[Root] = None
        try:
            old_root = await self.data_store.get_tree_root(tree_id=tree_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        wallet_current_generation = await self.data_store.get_validated_wallet_generation(tree_id)
        assert int(wallet_current_generation) <= singleton_record.generation
        # Wallet generation didn't change, so no new data committed on chain.
        if wallet_current_generation is not None and uint32(wallet_current_generation) == singleton_record.generation:
            self.log.info(f"Fetch data: wallet generation matching on-chain generation: {tree_id}.")
            return
        to_check: List[SingletonRecord] = []
        if subscription.mode is DownloadMode.LATEST:
            to_check = [singleton_record]
        if subscription.mode is DownloadMode.HISTORY:
            to_check = await self.wallet_rpc.dl_history(
                launcher_id=tree_id, min_generation=uint32(wallet_current_generation + 1)
            )
        # No root hash changes in the new wallet records, so ignore.
        # TODO: wallet should handle identical hashes part?
        if (
            old_root is not None
            and to_check[0].root == (old_root.node_hash if old_root.node_hash is not None else self.none_bytes)
            and len(set(record.root for record in to_check)) == 1
        ):
            await self.data_store.set_validated_wallet_generation(tree_id, int(singleton_record.generation))
            self.log.info(
                f"Fetch data: fast-forwarded for {tree_id} as all on-chain hashes are identical to our root hash. "
                f"Current wallet generation saved: {int(singleton_record.generation)}"
            )
            return
        # Delete all identical root hashes to our old root hash, until we detect a change.
        if old_root is not None:
            while to_check[-1].root == (old_root.node_hash if old_root.node_hash is not None else self.none_bytes):
                to_check.pop()

        self.log.info(
            f"Downloading and validating {subscription.tree_id}. "
            f"Current wallet generation: {int(wallet_current_generation)}. "
            f"Target wallet generation: {singleton_record.generation}."
        )

        try:
            downloaded = await download_data(self.data_store, subscription, singleton_record.root)
        except asyncio.CancelledError:
            raise
        except aiohttp.client_exceptions.ClientConnectorError:
            self.log.error(f"Server unavailable for {tree_id}.")
            downloaded = False
        except RuntimeError as e:
            self.log.error(f"Server sended invalid data for {tree_id}: {e}.")
            downloaded = False
        except Exception as e:
            self.log.error(f"Exception while downloading data for {tree_id}: {e}.")
            downloaded = False
        if not downloaded:
            await self.data_store.rollback_to_generation(tree_id, (0 if old_root is None else old_root.generation))
            raise RuntimeError("Could not download the data.")
        self.log.info(f"Successfully downloaded data for {tree_id}.")

        # Light validation: check the new set of operations against the new set of wallet records.
        # If this matches, we know all data will match, as we've previously checked that data matches
        # for `min_generation` data store root and `wallet_current_generation` wallet record.
        min_generation = (0 if old_root is None else old_root.generation) + 1
        try:
            is_valid: bool = await self._validate_batch(tree_id, to_check, min_generation)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.log.error(f"Error in validate batch for {tree_id}: {e}")
            is_valid = False

        # If for some reason we have mismatched data using the light checks, recheck all history as a fallback.
        if not is_valid:
            self.log.warning(f"Light validation failed for {tree_id}. Validating all history.")
            to_check = await self.wallet_rpc.dl_history(launcher_id=tree_id, min_generation=uint32(1))
            try:
                is_valid = await self._validate_batch(tree_id, to_check, 0)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log.error(f"Error in validate batch for {tree_id}: {e}")
                is_valid = False
            if not is_valid:
                await self.data_store.set_validated_wallet_generation(tree_id, 0)
                await self.data_store.rollback_to_generation(tree_id, 0)
                raise RuntimeError("Could not validate on-chain data. Downloading from scratch as a fallback.")

        self.log.info(
            f"Finished downloading and validating {subscription.tree_id}. "
            f"Wallet generation saved: {singleton_record.generation}. "
            f"Root hash saved: {singleton_record.root}."
        )
        await self.data_store.set_validated_wallet_generation(tree_id, int(singleton_record.generation))

    async def subscribe(self, store_id: bytes32, mode: DownloadMode, ip: str, port: uint16) -> None:
        subscription = Subscription(store_id, mode, ip, port)
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

    async def get_kv_diff(self, tree_id: bytes32, hash_1: bytes32, hash_2: bytes32) -> Set[DiffData]:
        return await self.data_store.get_kv_diff(tree_id, hash_1, hash_2)

    async def periodically_fetch_data(self) -> None:
        fetch_data_interval = self.config.get("fetch_data_interval", 60)
        while not self._shut_down:
            async with self.subscription_lock:
                subscriptions = await self.data_store.get_subscriptions()
                for subscription in subscriptions:
                    try:
                        await self.fetch_and_validate(subscription)
                    except Exception as e:
                        self.log.error(f"Exception while fetching data: {type(e)} {e} {traceback.format_exc()}.")
            try:
                await asyncio.sleep(fetch_data_interval)
            except asyncio.CancelledError:
                pass
