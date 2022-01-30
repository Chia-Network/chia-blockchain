import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Awaitable
import aiosqlite
import asyncio
from chia.data_layer.data_layer_types import InternalNode, TerminalNode, DownloadMode, Subscription, Root
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


class DataLayer:
    data_store: DataStore
    db_wrapper: DBWrapper
    db_path: Path
    connection: Optional[aiosqlite.Connection]
    config: Dict[str, Any]
    log: logging.Logger
    wallet_rpc_init: Awaitable[WalletRpcClient]
    state_changed_callback: Optional[Callable[..., object]]
    wallet_id: uint64
    initialized: bool

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

    def _set_state_changed_callback(self, callback: Callable[..., object]) -> None:
        self.state_changed_callback = callback

    def set_server(self, server: ChiaServer) -> None:
        self.server = server

    async def _start(self) -> bool:
        self.connection = await aiosqlite.connect(self.db_path)
        self.db_wrapper = DBWrapper(self.connection)
        self.data_store = await DataStore.create(self.db_wrapper)
        self.wallet_rpc = await self.wallet_rpc_init
        self.periodically_fetch_data_task: asyncio.Task[Any] = asyncio.create_task(self.periodically_fetch_data())
        self.subscription_lock: asyncio.Lock = asyncio.Lock()
        return True

    def _close(self) -> None:
        # TODO: review for anything else we need to do here
        self._shut_down = True
        self.periodically_fetch_data_task.cancel()

    async def _await_closed(self) -> None:
        if self.connection is not None:
            await self.connection.close()

    async def create_store(self) -> Tuple[List[TransactionRecord], bytes32]:
        # TODO: review for anything else we need to do here
        fee = uint64(1)
        root = bytes32([0] * 32)
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
    ) -> TransactionRecord:
        for change in changelist:
            if change["action"] == "insert":
                key = change["key"]
                value = change["value"]
                reference_node_hash = change.get("reference_node_hash")
                side = change.get("side")
                if reference_node_hash or side:
                    await self.data_store.insert(key, value, tree_id, reference_node_hash, side)
                await self.data_store.autoinsert(key, value, tree_id)
            else:
                assert change["action"] == "delete"
                key = change["key"]
                await self.data_store.delete(key, tree_id)

        await self.data_store.get_tree_root(tree_id)
        root = await self.data_store.get_tree_root(tree_id)
        # todo return empty node hash from get_tree_root
        if root.node_hash is not None:
            node_hash = root.node_hash
        else:
            node_hash = bytes32([0] * 32)  # todo change
        transaction_record = await self.wallet_rpc.dl_update_root(tree_id, node_hash)
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

    async def get_root(self, store_id: bytes32) -> Optional[bytes32]:
        res = await self.data_store.get_tree_root(tree_id=store_id)
        if res is None:
            self.log.error(f"Failed to get root for {store_id.hex()}")
            return None
        return res.node_hash

    async def fetch_and_validate(self, subscription: Subscription) -> None:
        tree_id = subscription.tree_id
        singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(tree_id)
        if singleton_record is None:
            return
        current_generation = await self.data_store.get_wallet_generation(tree_id)
        assert int(current_generation) <= singleton_record.generation
        if current_generation is not None and uint32(current_generation) == singleton_record.generation:
            return

        self.log.info(
            f"Downloading and validating {subscription.tree_id}. "
            f"Current wallet generation: {int(current_generation)}. "
            f"Target wallet generation: {singleton_record.generation}."
        )
        old_root: Optional[Root] = None
        if await self.data_store.tree_id_exists(tree_id=tree_id):
            old_root = await self.data_store.get_tree_root(tree_id=tree_id)
        to_check: List[SingletonRecord] = []
        if subscription.mode is DownloadMode.LATEST:
            to_check = [singleton_record]
        if subscription.mode is DownloadMode.HISTORY:
            to_check = await self.wallet_rpc.dl_history(launcher_id=tree_id, min_generation=current_generation + 1)

        downloaded = await self.data_store.download_data(subscription, singleton_record.root)
        if not downloaded:
            raise RuntimeError("Could not download the data.")

        root = await self.data_store.get_tree_root(tree_id=tree_id)
        if root.node_hash is None or root.node_hash != to_check[0].root:
            raise RuntimeError("Can't find data on chain in our datastore.")
        to_check.pop(0)
        min_generation = (0 if old_root is None else old_root.generation) + 1
        max_generation = root.generation

        for record in to_check:
            root_for_record = await self.data_store.get_last_tree_root_by_hash(tree_id, record.root, max_generation)
            if root_for_record is None or root_for_record.generation < min_generation:
                raise RuntimeError("Can't find data on chain in our datastore.")
            max_generation = root.generation

        self.log.info(
            f"Finished downloading and validating {subscription.tree_id}. "
            f"Wallet generation saved: {singleton_record.generation}"
            f"Root hash saved: {singleton_record.root}."
        )
        await self.data_store.set_wallet_generation(tree_id, int(singleton_record.generation))

    async def subscribe(self, store_id: bytes32, mode: DownloadMode, ip: str, port: uint16) -> None:
        subscription = Subscription(store_id, mode, ip, port)
        subscriptions = await self.get_subscriptions()
        if subscription.tree_id in [subscription.tree_id for subscription in subscriptions]:
            return
        await self.wallet_rpc.dl_track_new(subscription.tree_id)
        async with self.subscription_lock:
            await self.data_store.subscribe(subscription)
        self.log.info(f"Subscribed to {subscription.tree_id}")

    async def unsubscribe(self, tree_id: bytes32) -> None:
        subscriptions = await self.get_subscriptions()
        if tree_id not in [subscription.tree_id for subscription in subscriptions]:
            return
        async with self.subscription_lock:
            await self.data_store.unsubscribe(tree_id)
        await self.wallet_rpc.dl_stop_tracking(tree_id)
        self.log.info(f"Unsubscribed to {tree_id}")

    async def get_subscriptions(self) -> List[Subscription]:
        async with self.subscription_lock:
            return await self.data_store.get_subscriptions()

    async def periodically_fetch_data(self) -> None:
        fetch_data_interval = self.config.get("fetch_data_interval", 60)
        while not self._shut_down:
            async with self.subscription_lock:
                subscriptions = await self.data_store.get_subscriptions()
                for subscription in subscriptions:
                    await self.fetch_and_validate(subscription)
            try:
                await asyncio.sleep(fetch_data_interval)
            except asyncio.CancelledError:
                pass
