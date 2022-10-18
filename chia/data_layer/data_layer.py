from __future__ import annotations

import asyncio
import binascii
import json
import logging
import random
import time
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union

import aiohttp

from chia.data_layer.data_layer_errors import KeyNotFoundError
from chia.data_layer.data_layer_util import (
    DiffData,
    InternalNode,
    KeyValue,
    Layer,
    Offer,
    OfferStore,
    Proof,
    ProofOfInclusion,
    ProofOfInclusionLayer,
    Root,
    ServerInfo,
    Status,
    StoreProofs,
    Subscription,
    TerminalNode,
    leaf_hash,
)
from chia.data_layer.data_layer_wallet import DataLayerWallet, Mirror, SingletonRecord, verify_offer
from chia.data_layer.data_store import DataStore
from chia.data_layer.download_data import insert_from_delta_file, write_files_for_root
from chia.rpc.rpc_server import default_get_connections
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
from chia.data_layer.old_data import old_data


class DataLayer:
    data_store: DataStore
    db_path: Path
    config: Dict[str, Any]
    log: logging.Logger
    wallet_rpc_init: Awaitable[WalletRpcClient]
    state_changed_callback: Optional[Callable[..., object]]
    wallet_id: uint64
    initialized: bool
    none_bytes: bytes32
    lock: asyncio.Lock
    _server: Optional[ChiaServer]

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
        name: Optional[str] = None,
    ):
        if name == "":
            # TODO: If no code depends on "" counting as 'unspecified' then we do not
            #       need this.
            name = None
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
        self.none_bytes = bytes32([0] * 32)
        self.lock = asyncio.Lock()
        self._server = None

    def _set_state_changed_callback(self, callback: Callable[..., object]) -> None:
        self.state_changed_callback = callback

    async def on_connect(self, connection: WSChiaConnection) -> None:
        pass

    def get_connections(self, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

    def set_server(self, server: ChiaServer) -> None:
        self._server = server

    async def _start(self) -> None:
        self.data_store = await DataStore.create(database=self.db_path)
        self.wallet_rpc = await self.wallet_rpc_init
        self.subscription_lock: asyncio.Lock = asyncio.Lock()

        self.periodically_manage_data_task: asyncio.Task[Any] = asyncio.create_task(self.periodically_manage_data())

    def _close(self) -> None:
        # TODO: review for anything else we need to do here
        self._shut_down = True

    async def _await_closed(self) -> None:
        if self.connection is not None:
            await self.connection.close()
        try:
            self.periodically_manage_data_task.cancel()
        except asyncio.CancelledError:
            pass
        await self.data_store.close()

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
        return
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
                success = await insert_from_delta_file(
                    self.data_store,
                    tree_id,
                    root.generation,
                    [record.root for record in reversed(to_download)],
                    server_info,
                    self.server_files_location,
                    timeout,
                    self.log,
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

    async def add_missing_files(self, store_id: bytes32, overwrite: bool, foldername: Optional[Path]) -> None:
        root = await self.data_store.get_tree_root(tree_id=store_id)
        singleton_record: Optional[SingletonRecord] = await self.wallet_rpc.dl_latest_singleton(store_id, True)
        if singleton_record is None:
            self.log.error(f"No singleton record found for: {store_id}")
            return
        max_generation = min(singleton_record.generation, 0 if root is None else root.generation)
        server_files_location = foldername if foldername is not None else self.server_files_location
        for generation in range(1, max_generation + 1):
            root = await self.data_store.get_tree_root(tree_id=store_id, generation=generation)
            await write_files_for_root(self.data_store, store_id, root, server_files_location, overwrite)

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

    async def _check_all_confirmed(self, store_list: List[bytes32], expected_generation: int) -> bool:
        for tree_id in store_list:
            try:
                await self._update_confirmation_status(tree_id=tree_id)
                root = await self.data_store.get_tree_root(tree_id)
                if root.generation != expected_generation:
                    return False
            except Exception:
                return False
        return True

    async def migrate_data(self, fee: uint64) -> bytes32:
        stores_for_data: List[bytes32] = []
        new_store_to_org: Dict[bytes32, bytes32] = {}

        self.log.info("Migration: Creating singletons for stored data.")
        for org_dict in old_data:
            _, tree_id =await self.create_store(fee)
            self.log.info(f"Migration: Created tree_id: {tree_id}")
            stores_for_data.append(tree_id)
            new_store_to_org[tree_id] = bytes32.from_hexstr(org_dict["orgID"])
            await asyncio.sleep(3)

        while not await self._check_all_confirmed(stores_for_data, 0):            
            await asyncio.sleep(5)

        self.log.info("Migration: Created singletons for stored data.")
        self.log.info("Migration: Creating singletons for versioned data.")

        stores_for_version: List[bytes32] = []
        versioned_store_to_data: Dict[bytes32, bytese32] = {}
        for data_id in stores_for_data:
            _, tree_id = await self.create_store(fee)
            self.log.info(f"Migration: Created tree_id: {tree_id}")
            stores_for_version.append(tree_id)
            versioned_store_to_data[tree_id] = data_id

        while not await self._check_all_confirmed(stores_for_version, 0):            
            await asyncio.sleep(5)

        self.log.info("Migration: Created singletons for versioned data.")
        self.log.info("Migration: Uploading singletons with v1 version.")

        for versioned_store, data_store_id in versioned_store_to_data.items():
            batch: List[Dict[str, Any]] = []
            version = "v1"
            hex_data_store_id = data_store_id.hex()
            batch.append(
                {
                    "action": "insert",
                    "key": version.encode(),
                    "value": hex_data_store_id.encode(),
                }
            )
            await self.batch_update(versioned_store, batch, fee)
        
        while not await self._check_all_confirmed(stores_for_version, 1):            
            await asyncio.sleep(5)

        self.log.info("Migration: Uploaded singletons with v1 version.")
        self.log.info("Migration: Creating singletons for organisations.")

        stores_for_registry: List[bytes32] = []
        registry_store_to_versioned: Dict[bytes32, bytes32] = {}
        for versioned_store in stores_for_version:
            _, tree_id = await self.create_store(fee)
            self.log.info(f"Migration: Created tree_id: {tree_id}")
            stores_for_registry.append(tree_id)
            registry_store_to_versioned[tree_id] = versioned_store

        while not await self._check_all_confirmed(stores_for_registry, 0):            
            await asyncio.sleep(5)

        self.log.info("Migration: Created singletons for organisations.")
        self.log.info("Migration: Uploading organisation data to singletons.")

        for registry_store, versioned_store in registry_store_to_versioned.items():
            org_id = versioned_store_to_data[versioned_store]
            org_id = new_store_to_org[org_id]
            org_data = next(data for data in old_data if org_id.hex() == data["orgID"])
            batch: List[Dict[str, Any]] = []
            batch.append(
                {
                    "action": "insert",
                    "key": "name".encode(),
                    "value": bytes.fromhex(org_data["name"]),
                }
            )
            batch.append(
                {
                    "action": "insert",
                    "key": "icon".encode(),
                    "value": bytes.fromhex(org_data["icon"]),
                }
            )
            hex_versioned_store_id = versioned_store.hex()
            batch.append(
                {
                    "action": "insert",
                    "key": "registryId".encode(),
                    "value": hex_versioned_store_id.encode(),
                }
            )

            await self.batch_update(registry_store, batch, fee)

        while not await self._check_all_confirmed(stores_for_registry, 1):            
            await asyncio.sleep(5)

        self.log.info("Migration: Uploaded organisation data to singletons.")
        self.log.info("Migration: Uploading the units data to singleton.")
        for new_store, org in new_store_to_org.items():
            batch: List[Dict[str, Any]] = []
            org_data = next(data for data in old_data if data["orgID"] == org.hex())
            for k, v in org_data["registryData"].items():
                new_unit = json.loads(binascii.unhexlify(v).decode())
                if "orgUid" not in new_unit:
                    self.log.info(f"Migration: Don't have orgUid in the unit. {new_unit}")
                    batch.append(
                        {
                            "action": "insert",
                            "key": bytes.fromhex(k),
                            "value": bytes.fromhex(v),
                        }
                    )
                    continue
                if new_unit["orgUid"] != org.hex():
                    raise RuntimeError("Unit org doesn't match with organsation's data.")
                new_org = None
                for registry in stores_for_registry:
                    candidate_org = registry_store_to_versioned[registry]
                    candidate_org = versioned_store_to_data[candidate_org]
                    candidate_org = new_store_to_org[candidate_org]
                    if candidate_org == org:
                        new_org = registry
                        break
                if new_org is None:
                    raise RuntimeError("Can't find orgUid in initial list.")
                new_unit["orgUid"] = new_org.hex()
                new_unit_json = json.dumps(new_unit, separators=(',', ':'))
                batch.append(
                    {
                        "action": "insert",
                        "key": bytes.fromhex(k),
                        "value": new_unit_json.encode(),
                    }
                )
            await self.batch_update(new_store, batch, fee)

        while not await self._check_all_confirmed(stores_for_data, 1):            
            await asyncio.sleep(5)

        self.log.info("Migration: Uploaded the units data to singleton.")
        self.log.info("Migration: Creating gouvernance singleton.")

        _, gouvernance_tree_id = await self.create_store(fee)
        while not await self._check_all_confirmed([gouvernance_tree_id], 0):            
            await asyncio.sleep(5)

        self.log.info("Migration: Created gouvernance singleton.")
        self.log.info("Migration: Uploading gouvernance node data.")

        pick_list_key = "7069636b4c697374"
        pick_list_value = "7b2272656769737472696573223a5b22416d65726963616e20436172626f6e205265676973747279202841435229222c2241727469636c6520362e32204d656368616e69736d205265676973747279222c2241727469636c6520362e34204d656368616e69736d205265676973747279222c22436172626f6e204173736574732054726164696e672053797374656d20284341545329222c224368696c65204e6174696f6e616c205265676973747279222c22436c696d61746520416374696f6e2052657365727665202843415229222c22436f7374612052696361204e6174696f6e616c205265676973747279222c2245636f5265676973747279222c22476c6f62616c20436172626f6e20436f756e63696c222c22476f6c64205374616e64617264222c224a6f696e7420437265646974696e67204d656368616e69736d222c224d657869636f204e6174696f6e616c205265676973747279222c2253696e6761706f7265204e6174696f6e616c205265676973747279222c2253776564656e204e6174696f6e616c205265676973747279222c22537769747a65726c616e64204e6174696f6e616c205265676973747279222c22554e464343432043444d205265676973747279222c225665727261225d2c2270726f6a656374536563746f72223a5b224163636f6d6d6f646174696f6e20616e6420666f6f6420736572766963652061637469766974696573222c2241637469766974696573206f662065787472617465727269746f7269616c206f7267616e697a6174696f6e7320616e6420626f64696573222c2241637469766974696573206f6620686f757365686f6c647320617320656d706c6f796572733b20756e646966666572656e74696174656420676f6f64732d20616e642073657276696365732d70726f647563696e672061637469766974696573206f6620686f757365686f6c647320666f72206f776e20757365222c2241646d696e69737472617469766520616e6420737570706f727420736572766963652061637469766974696573222c224167726963756c747572653b20666f72657374727920616e642066697368696e67222c22417274732c20656e7465727461696e6d656e7420616e642072656372656174696f6e222c22436f6e737472756374696f6e222c22456475636174696f6e222c22456c6563747269636974793b206761732c20737465616d20616e642061697220636f6e646974696f6e696e6720737570706c79222c2246696e616e6369616c20616e6420696e737572616e63652061637469766974696573222c2248756d616e206865616c746820616e6420736f6369616c20776f726b2061637469766974696573222c22496e666f726d6174696f6e20616e6420636f6d6d756e69636174696f6e222c224d696e696e6720616e6420717561727279696e67222c224d616e75666163747572696e67222c224f7468657220736572766963652061637469766974696573222c2250726f66657373696f6e616c2c20736369656e746966696320616e6420746563686e6963616c2061637469766974696573222c225075626c69632061646d696e697374726174696f6e20616e6420646566656e63653b20636f6d70756c736f727920736f6369616c207365637572697479222c225265616c206573746174652061637469766974696573222c225472616e73706f72746174696f6e20616e642073746f72616765222c22576174657220737570706c793b2073657765726167652c207761737465206d616e6167656d656e7420616e642072656d6564696174696f6e2061637469766974696573222c2257686f6c6573616c6520616e642072657461696c2074726164653b20726570616972206f66206d6f746f722076656869636c657320616e64206d6f746f726379636c6573222c224e6f7420656c7365776865726520636c6173736966696564225d2c2270726f6a65637454797065223a5b224166666f726573746174696f6e222c2241766f69646564c2a0436f6e76657273696f6e222c22436f616cc2a04d696e65c2a04d657468616e65222c22436f6e736572766174696f6e222c22456e65726779c2a044656d616e64222c22466f726573747279222c22496d70726f766564c2a0466f72657374c2a04d616e6167656d656e74222c224c616e6466696c6cc2a0476173c2a0436170747572652f436f6d62757374696f6e222c224c69766573746f636b222c224e6974726f67656ec2a04d616e6167656d656e74222c224f7267616e6963c2a05761737465c2a0436f6d706f7374696e67222c224f7267616e6963c2a05761737465c2a0446967657374696f6e222c224f7a6f6e65c2a04465706c6574696e67c2a05375627374616e636573222c22506c6173746963c2a05761737465c2a0436f6c6c656374696f6e222c22506c6173746963c2a05761737465c2a052656379636c696e67222c22524544442b3ac2a052656475636564c2a0456d697373696f6e73c2a066726f6dc2a04465666f726573746174696f6ec2a0616e64c2a04465677261646174696f6e222c225265666f726573746174696f6ec2a0616e64c2a0526576656765746174696f6e222c225265666f726573746174696f6e222c22536f696cc2a0456e726963686d656e74225d2c22636f766572656442794e4443223a5b22496e73696465204e4443222c224f757473696465204e4443222c22556e6b6e6f776e225d2c2270726f6a65637453746174757356616c756573223a5b224c6973746564222c2256616c696461746564222c2252656769737465726564222c22417070726f766564222c22417574686f72697a6564222c22436f6d706c65746564222c225472616e736974696f6e6564222c2257697468647261776e222c2244652d72656769737465726564225d2c22756e69744d6574726963223a5b2274434f3265225d2c226d6574686f646f6c6f6779223a5b22414352202d20547275636b2053746f7020456c65637472696669636174696f6e222c22414352202d20416476616e6365642052656672696765726174696f6e2053797374656d73222c22414352202d20436572746966696564205265636c61696d656420484643205265667269676572616e74732c2050726f70656c6c616e74732c20616e642046697265205375707072657373616e7473222c22414352202d204465737472756374696f6e206f66204f7a6f6e65204465706c6574696e67205375627374616e63657320616e6420486967682d47575020466f616d222c22414352202d204465737472756374696f6e206f66204f7a6f6e65204465706c6574696e67205375627374616e6365732066726f6d20496e7465726e6174696f6e616c20536f7572636573222c22414352202d205472616e736974696f6e20746f20416476616e63656420466f726d756c6174696f6e20426c6f77696e67204167656e747320696e20466f616d204d616e75666163747572696e6720616e6420557365222c22414352202d204166666f726573746174696f6e20616e64205265666f726573746174696f6e206f66204465677261646564204c616e6473222c22414352202d2041766f6964656420436f6e76657273696f6e206f662047726173736c616e647320616e642053687275626c616e647320746f2043726f702050726f64756374696f6e222c22414352202d20496d70726f76656420466f72657374204d616e6167656d656e74202849464d29206f6e2043616e616469616e20466f726573746c616e6473222c22414352202d20496d70726f76656420466f72657374204d616e6167656d656e74202849464d29206f6e204e6f6e2d4665646572616c20552e532e20466f726573746c616e6473222c22414352202d20496d70726f76656420466f72657374204d616e6167656d656e74202849464d29206f6e20536d616c6c204e6f6e2d496e647573747269616c205072697661746520466f726573746c616e6473222c22414352202d20526573746f726174696f6e206f662043616c69666f726e69612044656c7461696320616e6420436f617374616c205765746c616e6473222c22414352202d20526573746f726174696f6e206f6620506f636f73696e205765746c616e6473222c22414352202d20436172626f6e204361707475726520616e642053746f726167652050726f6a65637473222c22414352202d204c616e6466696c6c20476173204465737472756374696f6e20616e642042656e6566696369616c205573652050726f6a65637473222c22434152202d2041646970696320416369642050726f64756374696f6e222c22434152202d2042696f63686172222c22434152202d2043616e6164612047726173736c616e64222c22434152202d20436f616c204d696e65204d657468616e65222c22434152202d20466f72657374222c22434152202d2047726173736c616e64222c22434152202d204d657869636f20426f696c657220456666696369656e6379222c22434152202d204d657869636f20466f72657374222c22434152202d204d657869636f2048616c6f636172626f6e222c22434152202d204d657869636f204c616e6466696c6c222c22434152202d204d657869636f204c69766573746f636b222c22434152202d204d657869636f204f7a6f6e65204465706c6574696e67205375627374616e636573222c22434152202d204e697472696320416369642050726f64756374696f6e222c22434152202d204e6974726f67656e204d616e6167656d656e74222c22434152202d204f7267616e696320576173746520436f6d706f7374696e67222c22434152202d204f7267616e696320576173746520446967657374696f6e222c22434152202d204f7a6f6e65204465706c6574696e67205375627374616e636573222c22434152202d20526963652043756c7469766174696f6e222c22434152202d20536f696c20456e726963686d656e74222c22434152202d20557262616e20466f72657374204d616e6167656d656e74222c22434152202d20557262616e205472656520506c616e74696e67222c22434152202d20552e532e204c616e6466696c6c222c22434152202d20552e532e204c69766573746f636b222c2243444d202d20414d30303031222c2243444d202d20414d30303037222c2243444d202d20414d30303039222c2243444d202d20414d30303137222c2243444d202d20414d30303138222c2243444d202d20414d30303139222c2243444d202d20414d30303230222c2243444d202d20414d30303231222c2243444d202d20414d30303233222c2243444d202d20414d30303236222c2243444d202d20414d30303237222c2243444d202d20414d30303238222c2243444d202d20414d30303330222c2243444d202d20414d30303331222c2243444d202d20414d30303335222c2243444d202d20414d30303336222c2243444d202d20414d30303337222c2243444d202d20414d30303338222c2243444d202d20414d30303433222c2243444d202d20414d30303434222c2243444d202d20414d30303435222c2243444d202d20414d30303436222c2243444d202d20414d30303438222c2243444d202d20414d30303439222c2243444d202d20414d30303530222c2243444d202d20414d30303532222c2243444d202d20414d30303533222c2243444d202d20414d30303535222c2243444d202d20414d30303536222c2243444d202d20414d30303537222c2243444d202d20414d30303538222c2243444d202d20414d30303539222c2243444d202d20414d30303630222c2243444d202d20414d30303631222c2243444d202d20414d30303632222c2243444d202d20414d30303633222c2243444d202d20414d30303634222c2243444d202d20414d30303635222c2243444d202d20414d30303636222c2243444d202d20414d30303637222c2243444d202d20414d30303638222c2243444d202d20414d30303639222c2243444d202d20414d30303730222c2243444d202d20414d30303731222c2243444d202d20414d30303732222c2243444d202d20414d30303733222c2243444d202d20414d30303734222c2243444d202d20414d30303735222c2243444d202d20414d30303736222c2243444d202d20414d30303737222c2243444d202d20414d30303738222c2243444d202d20414d30303739222c2243444d202d20414d30303830222c2243444d202d20414d30303831222c2243444d202d20414d30303832222c2243444d202d20414d30303833222c2243444d202d20414d30303834222c2243444d202d20414d30303836222c2243444d202d20414d30303838222c2243444d202d20414d30303839222c2243444d202d20414d30303930222c2243444d202d20414d30303931222c2243444d202d20414d30303932222c2243444d202d20414d30303933222c2243444d202d20414d30303934222c2243444d202d20414d30303935222c2243444d202d20414d30303936222c2243444d202d20414d30303937222c2243444d202d20414d30303938222c2243444d202d20414d30303939222c2243444d202d20414d30313030222c2243444d202d20414d30313031222c2243444d202d20414d30313033222c2243444d202d20414d30313034222c2243444d202d20414d30313035222c2243444d202d20414d30313036222c2243444d202d20414d30313037222c2243444d202d20414d30313038222c2243444d202d20414d30313039222c2243444d202d20414d30313130222c2243444d202d20414d30313131222c2243444d202d20414d30313132222c2243444d202d20414d30313133222c2243444d202d20414d30313134222c2243444d202d20414d30313135222c2243444d202d20414d30313136222c2243444d202d20414d30313137222c2243444d202d20414d30313138222c2243444d202d20414d30313139222c2243444d202d20414d30313230222c2243444d202d20414d30313231222c2243444d202d20414d30313232222c2243444d202d20414d532d492e412e222c2243444d202d20414d532d492e422e222c2243444d202d20414d532d492e432e222c2243444d202d20414d532d492e442e222c2243444d202d20414d532d492e452e222c2243444d202d20414d532d492e462e222c2243444d202d20414d532d492e472e222c2243444d202d20414d532d492e482e222c2243444d202d20414d532d492e492e222c2243444d202d20414d532d492e4a2e222c2243444d202d20414d532d492e4b2e222c2243444d202d20414d532d492e4c2e222c2243444d202d20414d532d492e4d2e222c2243444d202d20414d532d49492e412e222c2243444d202d20414d532d49492e422e222c2243444d202d20414d532d49492e432e222c2243444d202d20414d532d49492e442e222c2243444d202d20414d532d49492e452e222c2243444d202d20414d532d49492e462e222c2243444d202d20414d532d49492e472e222c2243444d202d20414d532d49492e482e222c2243444d202d20414d532d49492e492e222c2243444d202d20414d532d49492e4a2e222c2243444d202d20414d532d49492e4b2e222c2243444d202d20414d532d49492e4c2e222c2243444d202d20414d532d49492e4d2e222c2243444d202d20414d532d49492e4e2e222c2243444d202d20414d532d49492e4f2e222c2243444d202d20414d532d49492e502e222c2243444d202d20414d532d49492e512e222c2243444d202d20414d532d49492e522e222c2243444d202d20414d532d49492e532e222c2243444d202d20414d532d49492e542e222c2243444d202d20414d532d4949492e412e222c2243444d202d20414d532d4949492e422e222c2243444d202d20414d532d4949492e432e222c2243444d202d20414d532d4949492e442e222c2243444d202d20414d532d4949492e452e222c2243444d202d20414d532d4949492e462e222c2243444d202d20414d532d4949492e472e222c2243444d202d20414d532d4949492e482e222c2243444d202d20414d532d4949492e492e222c2243444d202d20414d532d4949492e4a2e222c2243444d202d20414d532d4949492e4b2e222c2243444d202d20414d532d4949492e4c2e222c2243444d202d20414d532d4949492e4d2e222c2243444d202d20414d532d4949492e4e2e222c2243444d202d20414d532d4949492e4f2e222c2243444d202d20414d532d4949492e502e222c2243444d202d20414d532d4949492e512e222c2243444d202d20414d532d4949492e522e222c2243444d202d20414d532d4949492e532e222c2243444d202d20414d532d4949492e542e222c2243444d202d20414d532d4949492e552e222c2243444d202d20414d532d4949492e562e222c2243444d202d20414d532d4949492e572e222c2243444d202d20414d532d4949492e582e222c2243444d202d20414d532d4949492e592e222c2243444d202d20414d532d4949492e5a2e222c2243444d202d20414d532d4949492e41412e222c2243444d202d20414d532d4949492e41422e222c2243444d202d20414d532d4949492e41432e222c2243444d202d20414d532d4949492e41442e222c2243444d202d20414d532d4949492e41452e222c2243444d202d20414d532d4949492e41462e222c2243444d202d20414d532d4949492e41472e222c2243444d202d20414d532d4949492e41482e222c2243444d202d20414d532d4949492e41492e222c2243444d202d20414d532d4949492e414a2e222c2243444d202d20414d532d4949492e414b2e222c2243444d202d20414d532d4949492e414c2e222c2243444d202d20414d532d4949492e414d2e222c2243444d202d20414d532d4949492e414e2e222c2243444d202d20414d532d4949492e414f2e222c2243444d202d20414d532d4949492e41502e222c2243444d202d20414d532d4949492e41512e222c2243444d202d20414d532d4949492e41522e222c2243444d202d20414d532d4949492e41532e222c2243444d202d20414d532d4949492e41542e222c2243444d202d20414d532d4949492e41552e222c2243444d202d20414d532d4949492e41562e222c2243444d202d20414d532d4949492e41572e222c2243444d202d20414d532d4949492e41582e222c2243444d202d20414d532d4949492e41592e222c2243444d202d20414d532d4949492e42412e222c2243444d202d20414d532d4949492e42422e222c2243444d202d20414d532d4949492e42432e222c2243444d202d20414d532d4949492e42442e222c2243444d202d20414d532d4949492e42452e222c2243444d202d20414d532d4949492e42462e222c2243444d202d20414d532d4949492e42472e222c2243444d202d20414d532d4949492e42482e222c2243444d202d20414d532d4949492e42492e222c2243444d202d20414d532d4949492e424a2e222c2243444d202d20414d532d4949492e424b2e222c2243444d202d20414d532d4949492e424c2e222c2243444d202d20414d532d4949492e424d2e222c2243444d202d20414d532d4949492e424e2e222c2243444d202d20414d532d4949492e424f2e222c2243444d202d20414d532d4949492e42502e222c2243444d202d2041522d414d30303134222c2243444d202d2041522d414d5330303033222c2243444d202d2041522d414d5330303037222c224753202d204d4554484f444f4c4f475920464f52204d4554455245442026204d4541535552454420454e4552475920434f4f4b494e472044455649434553222c224753202d204d4554484f444f4c4f475920464f5220524554524f46495420454e4552475920454646494349454e4359204d4541535552455320494e205348495050494e4720222c224753202d20534f494c204f5247414e494320434152424f4e204143544956495459204d4f44554c4520464f52204150504c49434154494f4e204f46204f5247414e494320534f494c20494d50524f564552532046524f4d2050554c5020414e44205041504552204d494c4c20534c5544474553222c224753202d205245445543454420454d495353494f4e532046524f4d20434f4f4b494e4720414e442048454154494e4720e2809320544543484e4f4c4f4749455320414e442050524143544943455320544f20444953504c41434520444543454e5452414c495a454420544845524d414c20454e4552475920434f4e53554d5054494f4e20285450444454454329222c224753202d20434152424f4e2053455155455354524154494f4e205448524f55474820414343454c45524154454420434152424f4e4154494f4e204f4620434f4e43524554452041474752454741544520222c224a434d202d20564e5f414d303135222c224a434d202d20564e5f414d303134222c224a434d202d20564e5f414d303133222c224a434d202d20564e5f414d303132222c224a434d202d20564e5f414d303131222c224a434d202d20564e5f414d303130222c224a434d202d20564e5f414d303039222c224a434d202d20564e5f414d303038222c224a434d202d20564e5f414d303037222c224a434d202d20564e5f414d303036222c224a434d202d20564e5f414d303035222c224a434d202d20564e5f414d303034222c224a434d202d20564e5f414d303033222c224a434d202d20564e5f414d303032222c224a434d202d20564e5f414d303031222c224a434d202d2054485f414d303137222c224a434d202d2054485f414d303136222c224a434d202d2054485f414d303135222c224a434d202d2054485f414d303134222c224a434d202d2054485f414d303133222c224a434d202d2054485f414d303132222c224a434d202d2054485f414d303131222c224a434d202d2054485f414d303130222c224a434d202d2054485f414d303039222c224a434d202d2054485f414d303038222c224a434d202d2054485f414d303037222c224a434d202d2054485f414d303036222c224a434d202d2054485f414d303035222c224a434d202d2054485f414d303034222c224a434d202d2054485f414d303033222c224a434d202d2054485f414d303032222c224a434d202d2054485f414d303031222c224a434d202d2053415f414d303031222c224a434d202d2050575f414d303031222c224a434d202d2050485f414d303032222c224a434d202d2050485f414d303031222c224a434d202d204d585f414d303031222c224a434d202d204d565f414d303032222c224a434d202d204d565f414d303031222c224a434d202d204d4e5f414d303033222c224a434d202d204d4e5f414d303032222c224a434d202d204d4e5f414d303031222c224a434d202d204d4d5f414d303035222c224a434d202d204d4d5f414d303034222c224a434d202d204d4d5f414d303033222c224a434d202d204d4d5f414d303032222c224a434d202d204d4d5f414d303031222c224a434d202d204c415f414d303034222c224a434d202d204c415f414d303033222c224a434d202d204c415f414d303032222c224a434d202d204c415f414d303031222c224a434d202d204b485f414d303035222c224a434d202d204b485f414d303034222c224a434d202d204b485f414d303033222c224a434d202d204b485f414d303032222c224a434d202d204b485f414d303031222c224a434d202d204b455f414d303033222c224a434d202d204b455f414d303032222c224a434d202d204b455f414d303031222c224a434d202d2049445f414d303238222c224a434d202d2049445f414d303237222c224a434d202d2049445f414d303236222c224a434d202d2049445f414d303235222c224a434d202d2049445f414d303234222c224a434d202d2049445f414d303233222c224a434d202d2049445f414d303232222c224a434d202d2049445f414d303231222c224a434d202d2049445f414d303230222c224a434d202d2049445f414d303139222c224a434d202d2049445f414d303138222c224a434d202d2049445f414d303137222c224a434d202d2049445f414d303136222c224a434d202d2049445f414d303135222c224a434d202d2049445f414d303134222c224a434d202d2049445f414d303133222c224a434d202d2049445f414d303132222c224a434d202d2049445f414d303131222c224a434d202d2049445f414d303130222c224a434d202d2049445f414d303039222c224a434d202d2049445f414d303038222c224a434d202d2049445f414d303037222c224a434d202d2049445f414d303036222c224a434d202d2049445f414d303035222c224a434d202d2049445f414d303034222c224a434d202d2049445f414d303033222c224a434d202d2049445f414d303032222c224a434d202d2049445f414d303031222c224a434d202d2045545f414d303033222c224a434d202d2045545f414d303032222c224a434d202d2045545f414d303031222c224a434d202d2043525f414d303033222c224a434d202d2043525f414d303032222c224a434d202d2043525f414d303031222c224a434d202d20434c5f414d303032222c224a434d202d20434c5f414d303031222c224a434d202d2042445f414d303033222c224a434d202d2042445f414d303032222c224a434d202d2042445f414d303031222c22564353202d20564d30303031222c22564353202d20564d30303032222c22564353202d20564d30303033222c22564353202d20564d30303034222c22564353202d20564d30303035222c22564353202d20564d30303036222c22564353202d20564d30303037222c22564353202d20564d30303038222c22564353202d20564d30303039222c22564353202d20564d30303130222c22564353202d20564d30303131222c22564353202d20564d30303132222c22564353202d20564d30303133222c22564353202d20564d30303134222c22564353202d20564d30303135222c22564353202d20564d30303136222c22564353202d20564d30303137222c22564353202d20564d30303138222c22564353202d20564d30303139222c22564353202d20564d30303230222c22564353202d20564d30303231222c22564353202d20564d30303232222c22564353202d20564d30303233222c22564353202d20564d30303234222c22564353202d20564d30303235222c22564353202d20564d30303236222c22564353202d20564d30303237222c22564353202d20564d30303238222c22564353202d20564d30303239222c22564353202d20564d30303330222c22564353202d20564d30303331222c22564353202d20564d30303332222c22564353202d20564d30303333222c22564353202d20564d30303334222c22564353202d20564d30303335222c22564353202d20564d30303336222c22564353202d20564d30303337222c22564353202d20564d30303338222c22564353202d20564d30303339222c22564353202d20564d30303430222c22564353202d20564d30303431222c22564353202d20564d30303432222c22564353202d20564d30303433222c22564353202d20564d52303030222c22564353202d20564d52303036225d2c2276616c69646174696f6e426f6479223a5b22344b20456172746820536369656e63652050726976617465204c696d69746564222c2241454e4f5220496e7465726e6174696f6e616c20532e412e552e222c22416772692d576173746520546563686e6f6c6f67792c20496e632e222c22417374657220476c6f62616c20456e7669726f6e6d656e74616c20536f6c7574696f6e732c20496e632e222c22436172626f6e20436865636b2028496e646961292050726976617465204c74642e222c224368696e61204275696c64696e67204d6174657269616c205465737420262043657274696669636174696f6e2047726f757020436f2e204c54442e202843544329222c224368696e6120436c617373696669636174696f6e20536f63696574792043657274696669636174696f6e20436f2e204c74642e20284343534329222c224368696e6120456e7669726f6e6d656e74616c20556e697465642043657274696669636174696f6e2043656e74657220436f2e2c204c74642e202843454329222c224368696e61205175616c6974792043657274696669636174696f6e2043656e746572202843514329222c22436f6c6f6d6269616e20496e7374697475746520666f7220546563686e6963616c205374616e646172647320616e642043657274696669636174696f6e202849434f4e54454329222c2245617274686f6f642053657276696365732050726976617465204c696d69746564222c22456e7669726f2d416363c3a87320496e632e222c2245504943205375737461696e6162696c697479205365727669636573205076742e204c74642e222c2245524d2043657274696669636174696f6e20616e6420566572696669636174696f6e205365727669636573204c74642e222c22466972737420456e7669726f6e6d656e742c20496e632e222c2247484420536572766963657320496e632e222c224b42532043657274696669636174696f6e205365727669636573205076742e204c74642e222c224c47414920546563686e6f6c6f676963616c2043656e7465722c20532e412e20284170706c75732b29222c22526520436172626f6e204c74642e222c2252494e4120536572766963657320532e702e41222c22527562792043616e796f6e20456e7669726f6e6d656e74616c2c20496e63222c2253264120436172626f6e2c204c4c43222c2253435320476c6f62616c205365727669636573222c225368656e7a68656e2043544920496e7465726e6174696f6e616c2043657274696669636174696f6e20436f2e2c204c7464202843544929222c2254c39c56204e6f7264204365727420476d6248222c2254c39c562053c39c4420536f75746820417369612050726976617465204c696d69746564225d2c22636f756e7472696573223a5b2241666768616e697374616e222c22416c62616e6961222c22416c6765726961222c22416e646f727261222c22416e676f6c61222c22416e746967756120616e642042617264756261222c22417267656e74696e61222c224175737472616c6961222c2241757374726961222c22417a65726261696a616e222c22426168616d6173222c224261687261696e222c2242616e676c6164657368222c224261726261646f73222c2242656c61727573222c2242656c6769756d222c2242656c697a65222c2242656e696e222c2242687574616e222c22426f6c69766961222c22426f736e696120616e6420204865727a65676f76696e61222c22426f747377616e61222c224272617a696c222c224272756e656920446172757373616c616d222c2242756c6761726961222c224275726b696e61204661736f222c22427572756e6469222c224361626f205665726465222c2243616d626f646961222c2243616d65726f6f6e222c2243616e616461222c2243656e7472616c204166726963616e2052657075626c6963222c2243686164222c224368696c65222c224368696e61222c22436f6c6f6d626961222c22436f6d6f726f73222c22436f6e676f222c22436f7374612052696361222c22436f746520642749766f697265222c2243726f61746961222c2243756261222c22437970727573222c22437a6563682052657075626c6963222c2244656d6f6372617469632050656f706c6527732052657075626c6963206f66204b6f726561222c2244656d6f6372617469632052657075626c6963206f6620436f6e676f222c2244656e6d61726b222c22446a69626f757469222c22446f6d696e696361222c22446f6d696e63616e2052657075626c6963222c224567797074222c22456c2053616c7661646f72222c2245717561746f7269616c204e6577204775696e6561222c2245726974726561222c224573746f6e6961222c22457468696f706961222c224575726f7065616e20556e696f6e222c2246696a69222c2246696e6c616e64222c224672616e6365222c224761626f6e222c2247656f72676961222c224765726d616e79222c224768616e61222c22477265656365222c224772656e616461222c2247756174656d616c61222c224775696e6561222c224775696e656120426973736175222c22477579616e61222c224861697469222c22486f6e6475726173222c2248756e67617279222c224963656c616e64222c22496e646961222c22496e646f6e65736961222c224972616e222c224972656c616e64222c2249737261656c222c224974616c79222c224a616d61696361222c224a6170616e222c224a6f7264616e222c224b656e7961222c224b69726962617469222c224b7577616974222c224c616f2050656f706c6527732044656d6f6372617469632052657075626c6963222c224c6174766961222c224c6562616e6f6e222c224c65736f74686f222c224c696265726961222c224c69627961222c224c6965636874656e737465696e222c224c69746875616e6961222c224c7578656d626f757267222c224d616461676173636172222c224d616c6179736961222c224d616c6469766573222c224d616c69222c224d616c7461222c224d61727368616c6c2049736c616e6473222c224d6175726974697573222c224d6175726974616e6961222c224d657869636f222c224d6963726f6e65736961222c224d6f6e61636f222c224d6f6e676f6c6961222c224d6f6e74656e6567726f222c224d6f726f63636f222c224d6f7a616d6269717565222c224d79616e6d6172222c224e616d69626961222c224e61757275222c224e6570616c222c224e65746865726c616e6473222c224e6577205a65616c616e64222c224e69676572222c224e6f72776179222c224f6d616e222c2250616b697374616e222c2250616c6175222c2250616e616d61222c225061707561204e6577204775696e6561222c225061726167756179222c2250657275222c225068696c697070696e6573222c22506f6c616e64222c22506f72747567616c222c225161746172222c2252657075626c6963206f66204b6f726561222c22526f6d616e6961222c225275737369616e2046656465726174696f6e222c225277616e6461222c225361696e74204b6974747320616e64204e65766973222c225361696e74204c75636961222c225361696e742056696e63656e7420616e6420746865204772656e6164696e6573222c2253616d6f61222c2253616e204d6172696e6f222c2253616f20546f6d6520616e64205072696e63697065222c22536175646920417261626961222c2253656e6567616c222c22536572626961222c2253696e6761706f7265222c22536c6f76616b6961222c22536c6f76656e6961222c22536f6c6f6d6f6e2049736c616e6473222c22536f6d616c6961222c22536f75746820416672696361222c22536f75746820537564616e222c22537061696e222c22537269204c616e6b61222c225374617465206f662050616c657374696e65222c22537564616e222c22537572696e616d65222c225377617a696c616e64222c2253776564656e222c22537769747a65726c616e64222c2254616a696b697374616e222c22546861696c616e64222c2254686520466f726d6572205975676f736c61762052657075626c6963206f66204d616365646f6e6961222c2254696d6f722d4c65737465222c22546f6e6761222c225472696e6964616420616e6420546f6261676f222c2254756e69736961222c225475726b6579222c22547576616c75222c225567616e6461222c22556b7261696e65222c22556e69746564204172616220456d697261746573222c22556e69746564204b696e67646f6d222c22556e697465642052657075626c6963206f662054616e7a616e6961222c22556e6974656420537461746573206f6620416d6572696361222c2255727567756179222c2256616e75617475222c2256656e657a75656c61222c2256696574204e616d222c225a696d6261627765225d2c22726174696e6754797065223a5b22434450222c2243435149222c224d414150222c2253796c76657261222c2242655a65726f225d2c22756e697454797065223a5b22526564756374696f6e202d206e6174757265222c22526564756374696f6e202d20746563686e6963616c222c2252656d6f76616c202d206e6174757265222c2252656d6f76616c202d20746563686e6963616c222c2241766f6964616e6365225d2c22756e6974537461747573223a5b2248656c64222c2252657469726564222c2243616e63656c6c6564222c2245787069726564222c22427566666572222c224578706f72746564222c2250656e64696e67204578706f7274225d2c22636f72726573706f6e64696e6741646a7573746d656e744465636c61726174696f6e223a5b22436f6d6d6974746564222c224e6f74205265717569726564222c22556e6b6e6f776e225d2c22636f72726573706f6e64696e6741646a7573746d656e74537461747573223a5b224e6f742053746172746564222c2250656e64696e67222c22436f6d706c65746564225d2c226c6162656c54797065223a5b2243657274696669636174696f6e222c22456e646f7273656d656e74222c224c6574746572206f6620417070726f76616c222c224c6574746572206f6620417574686f72697a6174696f6e222c224c6574746572206f66205175616c696669636174696f6e225d2c22766572696669636174696f6e426f6479223a5b22344b20456172746820536369656e63652050726976617465204c696d697465642028344b455329222c2241454e4f5220494e5445524e4143494f4e414c2c20532e412e552e202841454e4f5229222c22416772692d576173746520546563686e6f6c6f67792c20496e632e222c2241736f6369616369c3b36e206465204e6f726d616c697a616369c3b36e2079204365727469666963616369c3b36e2c20412e432e222c22417374657220476c6f62616c20456e7669726f6e6d656e74616c20536f6c7574696f6e732c20496e632e222c22427572656175205665726974617320496e646961205076742e204c74642e202842564929222c22436172626f6e20436865636b2028496e646961292050726976617465204c74642e2028436172626f6e20436865636b29222c224345505245492063657274696669636174696f6e20626f6479202843455052454929222c224368696e612043657274696669636174696f6e2043656e7465722c496e632e20284343434929222c224368696e6120436c617373696669636174696f6e20536f63696574792043657274696669636174696f6e20436f2e2c204c74642e20284343534329222c224368696e6120456e7669726f6e6d656e74616c20556e697465642043657274696669636174696f6e2043656e74657220436f2e2c204c74642e202843454329222c224368696e61205175616c6974792043657274696669636174696f6e2043656e746572202843514329222c224368696e612054657374696e6720262043657274696669636174696f6e20496e7465726e6174696f6e616c2047726f757020436f2e2c204c74642e202843544329222c22436f6c6f6d6269616e20496e7374697475746520666f7220546563686e6963616c205374616e646172647320616e642043657274696669636174696f6e202849434f4e54454329222c2244656c6f6974746520546f686d61747375205375737461696e6162696c6974792c20436f2e2c204c74642e2028445453555329222c22446574204e6f72736b6520566572697461732028552e532e412e292c20496e632e222c2245617274686f6f642053657276696365732050726976617465204c696d69746564202845617274686f6f6429222c22456e7669726f2d416363c3a87320496e632e222c22456e7669726f6e6d656e74616c2053657276696365732c20496e632e222c2245504943205375737461696e6162696c697479205365727669636573205076742e204c74642e20284550494329222c2245524d2043657274696669636174696f6e20616e6420566572696669636174696f6e205365727669636573204c696d69746564202845524d2043565329222c22466972737420456e7669726f6e6d656e742c20496e632e222c22474844204c696d69746564202847484429222c224a6170616e205175616c697479204173737572616e6365204f7267616e69736174696f6e20284a514129222c224b42532043657274696669636174696f6e205365727669636573205076742e204c746420284b425329222c224b6f72656120456e65726779204167656e637920284b454129222c224b6f7265612054657374696e67202620526573656172636820496e7374697475746520284b545229222c224b6f7265616e20466f756e646174696f6e20666f72205175616c69747920284b465129222c224b6f7265616e205374616e6461726473204173736f63696174696f6e20284b534129222c224c47414920546563686e6f6c6f676963616c2043656e74657220532e412e222c225261696e666f7265737420416c6c69616e63652c20496e632e222c22526520436172626f6e2047c3b67a6574696d2044656e6574696d2076652042656c67656c656e6469726d65204c696d69746564205369726b6574692028526520436172626f6e29222c2252494e4120536572766963657320532e702e412e202852494e4129222c22527562792043616e796f6e20456e7669726f6e6d656e74616c2c20496e63222c2253264120436172626f6e2c204c4c43222c2253435320476c6f62616c205365727669636573222c225368656e7a68656e2043544920496e7465726e6174696f6e616c2043657274696669636174696f6e20436f2e2c204c7464222c22546865204561727468204c6162222c2254c39c56204e4f5244204345525420476d6248202854c39c56204e4f524429222c2254c39c562053c39c4420536f75746820417369612050726976617465204c696d69746564222c2256657269636f20534345222c22564b552043657274696669636174696f6e205076742e204c74642e225d2c2270726f6a65637454616773223a5b2242696f646976657273697479222c225265666f726573746174696f6e222c22456e6572677920656666696369656e6379222c22456e65726779207265646973747269627574696f6e222c225375737461696e61626c6520707261637469636573225d2c22756e697454616773223a5b2242696f646976657273697479222c225265666f726573746174696f6e222c22456e6572677920656666696369656e6379222c22456e65726779207265646973747269627574696f6e222c225375737461696e61626c6520707261637469636573225d2c22636f42656e6566697473223a5b225344472031202d204e6f20706f7665727479222c225344472032202d205a65726f2068756e676572222c225344472033202d20476f6f64206865616c746820616e642077656c6c2d6265696e67222c225344472034202d205175616c69747920656475636174696f6e222c225344472035202d2047656e64657220657175616c697479222c225344472036202d20436c65616e20776174657220616e642073616e69746174696f6e222c225344472037202d204166666f726461626c6520616e6420636c65616e20656e65726779222c225344472038202d20446563656e7420776f726b20616e642065636f6e6f6d69632067726f777468222c225344472039202d20496e6475737472792c20696e6e6f766174696f6e2c20616e6420696e667261737472756374757265222c22534447203130202d205265647563656420696e657175616c6974696573222c22534447203131202d205375737461696e61626c652063697469657320616e6420636f6d6d756e6974696573222c22534447203132202d20526573706f6e7369626c6520636f6e73756d7074696f6e20616e642070726f64756374696f6e222c22534447203133202d20436c696d61746520616374696f6e222c22534447203134202d204c6966652062656c6f77207761746572222c22534447203135202d204c696665206f6e206c616e64222c22534447203136202d20506561636520616e64206a757374696365207374726f6e6720696e737469747574696f6e73222c22534447203137202d20506172746e6572736869707320666f722074686520676f616c73225d7d"

        batch = [
            {
                "action": "insert",
                "key": bytes.fromhex(pick_list_key),
                "value": bytes.fromhex(pick_list_value),
            }
        ]

        organisations = []
        for org in stores_for_registry:
            organisations.append(
                {
                    "orgUid": org.hex(),
                    "ip": "52.11.178.69",
                    "port": 8575,
                }
            )

        orgs_str = json.dumps(organisations, separators=(',', ':'))
        batch.append(
            {
                "action": "insert",
                "key": bytes.fromhex("6f72674c697374"),
                "value": orgs_str.encode(),
            }
        )

        await self.batch_update(gouvernance_tree_id, batch, fee)
        while not await self._check_all_confirmed([gouvernance_tree_id], 1):            
            await asyncio.sleep(5)

        self.log.info("Migration: Uploaded gouvernance node data.")
        return gouvernance_tree_id
