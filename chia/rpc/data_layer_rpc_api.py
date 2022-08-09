from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar, Union

from typing_extensions import Protocol, final

from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_util import ProofOfInclusion, Side, Subscription, leaf_hash
from chia.rpc.rpc_server import Endpoint, EndpointResult
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes

# todo input assertions for all rpc's
from chia.util.ints import uint32, uint64
from chia.util.streamable import recurse_jsonify
from chia.wallet.trading.offer import Offer as TradingOffer


@final
@dataclasses.dataclass(frozen=True)
class KeyValue:
    key: bytes
    value: bytes

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> KeyValue:
        return cls(
            key=hexstr_to_bytes(marshalled["key"]),
            value=hexstr_to_bytes(marshalled["value"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "key": self.key.hex(),
            "value": self.value.hex(),
        }


@dataclasses.dataclass(frozen=True)
class OfferStore:
    store_id: bytes32
    inclusions: Tuple[KeyValue, ...]

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> OfferStore:
        return cls(
            store_id=bytes32.from_hexstr(marshalled["store_id"]),
            inclusions=tuple(KeyValue.unmarshal(key_value) for key_value in marshalled["inclusions"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "store_id": self.store_id.hex(),
            "inclusions": [key_value.marshal() for key_value in self.inclusions],
        }


# TODO: repeats chia.data_layer.data_layer_util.ProofOfInclusionLayer
@dataclasses.dataclass(frozen=True)
class Layer:
    other_hash_side: Side
    other_hash: bytes32
    # TODO: redundant?
    combined_hash: bytes32

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> Layer:
        return cls(
            other_hash_side=Side.unmarshal(marshalled["other_hash_side"]),
            other_hash=bytes32.from_hexstr(marshalled["other_hash"]),
            combined_hash=bytes32.from_hexstr(marshalled["combined_hash"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "other_hash_side": self.other_hash_side.marshal(),
            "other_hash": self.other_hash.hex(),
            "combined_hash": self.combined_hash.hex(),
        }


@dataclasses.dataclass(frozen=True)
class MakeOfferRequest:
    maker: Tuple[OfferStore, ...]
    taker: Tuple[OfferStore, ...]
    # TODO: handle a fee

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> MakeOfferRequest:
        return cls(
            maker=tuple(OfferStore.unmarshal(offer_store) for offer_store in marshalled["maker"]),
            taker=tuple(OfferStore.unmarshal(offer_store) for offer_store in marshalled["taker"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "maker": [offer_store.marshal() for offer_store in self.maker],
            "taker": [offer_store.marshal() for offer_store in self.taker],
        }


@dataclasses.dataclass(frozen=True)
class Proof:
    key: bytes
    value: bytes
    # TODO: redundant?
    node_hash: bytes32
    layers: Tuple[Layer, ...]

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> Proof:
        return cls(
            key=hexstr_to_bytes(marshalled["key"]),
            value=hexstr_to_bytes(marshalled["value"]),
            node_hash=bytes32.from_hexstr(marshalled["node_hash"]),
            layers=tuple(Layer.unmarshal(layer) for layer in marshalled["layers"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "key": self.key.hex(),
            "value": self.value.hex(),
            "node_hash": self.node_hash.hex(),
            "layers": [layer.marshal() for layer in self.layers],
        }


@dataclasses.dataclass(frozen=True)
class StoreProofs:
    store_id: bytes32
    proofs: Tuple[Proof, ...]

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> StoreProofs:
        return cls(
            store_id=bytes32.from_hexstr(marshalled["store_id"]),
            proofs=tuple(Proof.unmarshal(proof) for proof in marshalled["proofs"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "store_id": self.store_id.hex(),
            "proofs": [proof.marshal() for proof in self.proofs],
        }


@dataclasses.dataclass(frozen=True)
class Offer:
    # TODO: enforce bech32m and prefix?
    offer_id: bytes
    offer: bytes
    taker: Tuple[OfferStore, ...]
    maker: Tuple[StoreProofs, ...]

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> Offer:
        return cls(
            offer_id=bytes32.from_hexstr(marshalled["offer_id"]),
            offer=hexstr_to_bytes(marshalled["offer"]),
            taker=tuple(OfferStore.unmarshal(offer_store) for offer_store in marshalled["taker"]),
            maker=tuple(StoreProofs.unmarshal(store_proof) for store_proof in marshalled["maker"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "offer_id": self.offer_id.hex(),
            "offer": self.offer.hex(),
            "taker": [offer_store.marshal() for offer_store in self.taker],
            "maker": [store_proofs.marshal() for store_proofs in self.maker],
        }


@dataclasses.dataclass(frozen=True)
class MakeOfferResponse:
    success: bool
    offer: Offer

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> MakeOfferResponse:
        return cls(
            success=marshalled["success"],
            offer=Offer.unmarshal(marshalled["offer"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "offer": self.offer.marshal(),
        }


@dataclasses.dataclass(frozen=True)
class TakeOfferRequest:
    offer: Offer

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> TakeOfferRequest:
        return cls(
            offer=Offer.unmarshal(marshalled["offer"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "offer": self.offer.marshal(),
        }


@dataclasses.dataclass(frozen=True)
class TakeOfferResponse:
    success: bool
    transaction_id: bytes32

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> TakeOfferResponse:
        return cls(
            success=marshalled["success"],
            transaction_id=bytes32.from_hexstr(marshalled["transaction_id"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "transaction_id": self.transaction_id.hex(),
        }


_T = TypeVar("_T")


class MarshallableProtocol(Protocol):
    @classmethod
    def unmarshal(cls: Type[_T], marshalled: Dict[str, Any]) -> _T:
        ...

    def marshal(self) -> Dict[str, Any]:
        ...


class UnboundRoute(Protocol):
    async def __call__(self, request: Dict[str, Any]) -> Dict[str, object]:
        pass


class UnboundMarshalledRoute(Protocol):
    # Ignoring pylint complaint about the name of the first argument since this is a
    # special case.
    async def __call__(  # pylint: disable=E0213
        protocol_self, self: Any, request: MarshallableProtocol
    ) -> MarshallableProtocol:
        pass


class RouteDecorator(Protocol):
    def __call__(self, route: UnboundMarshalledRoute) -> UnboundRoute:
        pass


# TODO: move elsewhere if this is going to survive
def marshal() -> RouteDecorator:
    def decorator(route: UnboundMarshalledRoute) -> UnboundRoute:
        from typing import get_type_hints

        hints = get_type_hints(route)
        request_class: Type[MarshallableProtocol] = hints["request"]

        async def wrapper(self: object, request: Dict[str, object]) -> Dict[str, object]:
            unmarshalled_request = request_class.unmarshal(request)

            response = await route(self, request=unmarshalled_request)

            return response.marshal()

        # type ignoring since mypy is having issues with bound vs. unbound methods
        return wrapper  # type: ignore[return-value]

    return decorator


def process_change(change: Dict[str, Any]) -> Dict[str, Any]:
    # TODO: A full class would likely be nice for this so downstream doesn't
    #       have to deal with maybe-present attributes or Dict[str, Any] hints.
    reference_node_hash = change.get("reference_node_hash")
    if reference_node_hash is not None:
        reference_node_hash = bytes32(hexstr_to_bytes(reference_node_hash))

    side = change.get("side")
    if side is not None:
        side = Side(side)

    value = change.get("value")
    if value is not None:
        value = hexstr_to_bytes(value)

    return {
        **change,
        "key": hexstr_to_bytes(change["key"]),
        "value": value,
        "reference_node_hash": reference_node_hash,
        "side": side,
    }


def get_fee(config: Dict[str, Any], request: Dict[str, Any]) -> uint64:
    fee = request.get("fee")
    if fee is None:
        config_fee = config.get("fee", 0)
        return uint64(config_fee)
    return uint64(fee)


class DataLayerRpcApi:
    # TODO: other RPC APIs do not accept a wallet and the service start does not expect to provide one
    def __init__(self, data_layer: DataLayer):  # , wallet: DataLayerWallet):
        self.service: DataLayer = data_layer
        self.service_name = "chia_data_layer"

    def get_routes(self) -> Dict[str, Endpoint]:
        return {
            "/create_data_store": self.create_data_store,
            "/get_owned_stores": self.get_owned_stores,
            "/batch_update": self.batch_update,
            "/get_value": self.get_value,
            "/get_keys": self.get_keys,
            "/get_keys_values": self.get_keys_values,
            "/get_ancestors": self.get_ancestors,
            "/get_root": self.get_root,
            "/get_local_root": self.get_local_root,
            "/get_roots": self.get_roots,
            "/delete_key": self.delete_key,
            "/insert": self.insert,
            "/subscribe": self.subscribe,
            "/unsubscribe": self.unsubscribe,
            "/subscriptions": self.subscriptions,
            "/get_kv_diff": self.get_kv_diff,
            "/get_root_history": self.get_root_history,
            "/add_missing_files": self.add_missing_files,
            "/make_offer": self.make_offer,
            "/take_offer": self.take_offer,
        }

    async def create_data_store(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        fee = get_fee(self.service.config, request)
        txs, value = await self.service.create_store(uint64(fee))
        return {"txs": txs, "id": value.hex()}

    async def get_owned_stores(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        singleton_records = await self.service.get_owned_stores()
        return {"store_ids": [singleton.launcher_id.hex() for singleton in singleton_records]}

    async def get_value(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = bytes32.from_hexstr(request["id"])
        key = hexstr_to_bytes(request["key"])
        if self.service is None:
            raise Exception("Data layer not created")
        value = await self.service.get_value(store_id=store_id, key=key)
        hex = None
        if value is not None:
            hex = value.hex()
        return {"value": hex}

    async def get_keys(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = bytes32.from_hexstr(request["id"])
        root_hash = request.get("root_hash")
        if root_hash is not None:
            root_hash = bytes32.from_hexstr(root_hash)
        if self.service is None:
            raise Exception("Data layer not created")
        keys = await self.service.get_keys(store_id, root_hash)
        return {"keys": [f"0x{key.hex()}" for key in keys]}

    async def get_keys_values(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        root_hash = request.get("root_hash")
        if root_hash is not None:
            root_hash = bytes32.from_hexstr(root_hash)
        if self.service is None:
            raise Exception("Data layer not created")
        res = await self.service.get_keys_values(store_id, root_hash)
        json_nodes = []
        for node in res:
            json = recurse_jsonify(dataclasses.asdict(node))
            json_nodes.append(json)
        return {"keys_values": json_nodes}

    async def get_ancestors(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        node_hash = bytes32.from_hexstr(request["hash"])
        if self.service is None:
            raise Exception("Data layer not created")
        value = await self.service.get_ancestors(node_hash, store_id)
        return {"ancestors": value}

    async def batch_update(self, request: Dict[str, Any]) -> EndpointResult:
        """
        id  - the id of the store we are operating on
        changelist - a list of changes to apply on store
        """
        fee = get_fee(self.service.config, request)
        changelist = [process_change(change) for change in request["changelist"]]
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        transaction_record = await self.service.batch_update(store_id, changelist, uint64(fee))
        if transaction_record is None:
            raise Exception(f"Batch update failed for: {store_id}")
        return {"tx_id": transaction_record.name}

    async def insert(self, request: Dict[str, Any]) -> EndpointResult:
        """
        rows_to_add a list of clvm objects as bytes to add to talbe
        rows_to_remove a list of row hashes to remove
        """
        fee = get_fee(self.service.config, request)
        key = hexstr_to_bytes(request["key"])
        value = hexstr_to_bytes(request["value"])
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        changelist = [{"action": "insert", "key": key, "value": value}]
        transaction_record = await self.service.batch_update(store_id, changelist, uint64(fee))
        return {"tx_id": transaction_record.name}

    async def delete_key(self, request: Dict[str, Any]) -> EndpointResult:
        """
        rows_to_add a list of clvm objects as bytes to add to talbe
        rows_to_remove a list of row hashes to remove
        """
        fee = get_fee(self.service.config, request)
        key = hexstr_to_bytes(request["key"])
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        changelist = [{"action": "delete", "key": key}]
        transaction_record = await self.service.batch_update(store_id, changelist, uint64(fee))
        return {"tx_id": transaction_record.name}

    async def get_root(self, request: Dict[str, Any]) -> EndpointResult:
        """get hash of latest tree root"""
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        rec = await self.service.get_root(store_id)
        if rec is None:
            raise Exception(f"Failed to get root for {store_id.hex()}")
        return {"hash": rec.root, "confirmed": rec.confirmed, "timestamp": rec.timestamp}

    async def get_local_root(self, request: Dict[str, Any]) -> EndpointResult:
        """get hash of latest tree root saved in our local datastore"""
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        res = await self.service.get_local_root(store_id)
        return {"hash": res}

    async def get_roots(self, request: Dict[str, Any]) -> EndpointResult:
        """
        get state hashes for a list of roots
        """
        store_ids = request["ids"]
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        roots = []
        for id in store_ids:
            id_bytes = bytes32.from_hexstr(id)
            rec = await self.service.get_root(id_bytes)
            if rec is not None:
                roots.append({"id": id_bytes, "hash": rec.root, "confirmed": rec.confirmed, "timestamp": rec.timestamp})
        return {"root_hashes": roots}

    async def subscribe(self, request: Dict[str, Any]) -> EndpointResult:
        """
        subscribe to singleton
        """
        store_id = request.get("id")
        if store_id is None:
            raise Exception("missing store id in request")

        if self.service is None:
            raise Exception("Data layer not created")
        store_id_bytes = bytes32.from_hexstr(store_id)
        urls = request["urls"]
        await self.service.subscribe(store_id=store_id_bytes, urls=urls)
        return {}

    async def unsubscribe(self, request: Dict[str, Any]) -> EndpointResult:
        """
        unsubscribe from singleton
        """
        store_id = request.get("id")
        if store_id is None:
            raise Exception("missing store id in request")
        if self.service is None:
            raise Exception("Data layer not created")
        store_id_bytes = bytes32.from_hexstr(store_id)
        await self.service.unsubscribe(store_id_bytes)
        return {}

    async def subscriptions(self, request: Dict[str, Any]) -> EndpointResult:
        """
        List current subscriptions
        """
        if self.service is None:
            raise Exception("Data layer not created")
        subscriptions: List[Subscription] = await self.service.get_subscriptions()
        return {"store_ids": [sub.tree_id.hex() for sub in subscriptions]}

    async def add_missing_files(self, request: Dict[str, Any]) -> EndpointResult:
        """
        complete the data server files.
        """
        if "ids" in request:
            store_ids = request["ids"]
            ids_bytes = [bytes32.from_hexstr(id) for id in store_ids]
        else:
            subscriptions: List[Subscription] = await self.service.get_subscriptions()
            ids_bytes = [subscription.tree_id for subscription in subscriptions]
        override = request.get("override", False)
        foldername: Optional[Path] = None
        if "foldername" in request:
            foldername = Path(request["foldername"])
        for tree_id in ids_bytes:
            await self.service.add_missing_files(tree_id, override, foldername)
        return {}

    async def get_root_history(self, request: Dict[str, Any]) -> EndpointResult:
        """
        get history of state hashes for a store
        """
        if self.service is None:
            raise Exception("Data layer not created")
        store_id = request["id"]
        id_bytes = bytes32.from_hexstr(store_id)
        records = await self.service.get_root_history(id_bytes)
        res: List[Dict[str, Any]] = []
        for rec in records:
            res.insert(0, {"root_hash": rec.root, "confirmed": rec.confirmed, "timestamp": rec.timestamp})
        return {"root_history": res}

    async def get_kv_diff(self, request: Dict[str, Any]) -> EndpointResult:
        """
        get kv diff between two root hashes
        """
        if self.service is None:
            raise Exception("Data layer not created")
        store_id = request["id"]
        id_bytes = bytes32.from_hexstr(store_id)
        hash_1 = request["hash_1"]
        hash_1_bytes = bytes32.from_hexstr(hash_1)
        hash_2 = request["hash_2"]
        hash_2_bytes = bytes32.from_hexstr(hash_2)
        records = await self.service.get_kv_diff(id_bytes, hash_1_bytes, hash_2_bytes)
        res: List[Dict[str, Any]] = []
        for rec in records:
            res.insert(0, {"type": rec.type.name, "key": rec.key.hex(), "value": rec.value.hex()})
        return {"diff": res}

    # TODO: figure out the hinting
    @marshal()  # type: ignore[arg-type]
    async def make_offer(self, request: MakeOfferRequest) -> MakeOfferResponse:
        # TODO: should the StoreProofs include the root?
        our_store_roots: Dict[bytes32, bytes32] = {}
        our_store_proofs: List[StoreProofs] = []
        for offer_store in request.maker:
            # TODO: handle upserts?  deletes?
            changelist = [
                {
                    "action": "insert",
                    "key": entry.key,
                    "value": entry.value,
                }
                for entry in offer_store.inclusions
            ]
            # TODO: am i reaching too far down here?  can't use DataLayer.batch_update()
            #       since it publishes to chain.
            new_root_hash = await self.service.data_store.insert_batch(
                tree_id=offer_store.store_id,
                changelist=changelist,
            )
            if new_root_hash is None:
                raise Exception("only inserts are supported so a None root hash should not be possible")
            our_store_roots[offer_store.store_id] = new_root_hash

            proofs: List[Proof] = []
            for entry in offer_store.inclusions:
                # TODO: am i reaching too far down here?
                node = await self.service.data_store.get_node_by_key(
                    tree_id=offer_store.store_id, key=entry.key, root_hash=new_root_hash
                )
                # TODO: gets nothing, maybe because the ancestors are not calculated
                #       yet due to waiting for non-pending state?  maybe?
                #       (see: 840910390980427)
                proof_of_inclusion = await self.service.data_store.get_proof_of_inclusion_by_hash(
                    node_hash=node.hash, tree_id=offer_store.store_id, root_hash=new_root_hash
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
            our_store_proofs.append(store_proof)

        # TODO: make the -1/1 not just misc literals
        stores: Dict[Union[uint32, str], int] = {
            **{offer_store.store_id.hex(): -1 for offer_store in request.maker},
            **{offer_store.store_id.hex(): 1 for offer_store in request.taker},
        }

        solver: Dict[str, Any] = {
            our_offer_store.store_id.hex(): {
                "new_root": "0x" + our_store_roots[our_offer_store.store_id].hex(),
                "dependencies": [
                    {
                        # TODO: required 0x :[
                        "launcher_id": "0x" + their_offer_store.store_id.hex(),
                        "values_to_prove": [
                            "0x" + leaf_hash(key=entry.key, value=entry.value).hex()
                            for entry in their_offer_store.inclusions
                        ],
                    }
                    for their_offer_store in request.taker
                ],
            }
            for our_offer_store in request.maker
        }

        # {
        #     offer_store.store_id.hex(): {
        #         "type": AssetType.SINGLETON.value,
        #         "launcher_id": "0x" + offer_store.store_id.hex(),
        #         "launcher_ph": "0x" + SINGLETON_LAUNCHER_HASH.hex(),
        #         "also": {
        #             "type": AssetType.METADATA.value,
        #             "metadata": f"(0x{needs_the_root.hex()} . ())",
        #             "updater_hash": "0x" + ACS_MU_PH.hex(),
        #         },
        #     }
        #     for offer_store in [*request.taker]
        # }

        offer, trade_record = await self.service.wallet_rpc.create_offer_for_ids(
            offer_dict=stores,
            solver=solver,
            driver_dict={},
            # TODO: handle the fee
            fee=0,
            validate_only=False,
        )
        # TODO: WalletRpcApi.create_offer_for_ids() returns None when you
        #       validate_only=True.  consider changing api.
        if offer is None:
            raise Exception("offer is None despite validate_only=False")

        return MakeOfferResponse(
            success=True,
            offer=Offer(
                offer_id=trade_record.trade_id, offer=bytes(offer), taker=request.taker, maker=tuple(our_store_proofs)
            ),
        )

    # TODO: figure out the hinting
    @marshal()  # type: ignore[arg-type]
    async def take_offer(self, request: TakeOfferRequest) -> TakeOfferResponse:
        # TODO: should the StoreProofs include the root?
        our_store_roots: Dict[bytes32, bytes32] = {}
        our_store_proofs: List[StoreProofs] = []
        for offer_store in request.offer.taker:
            # TODO: handle upserts?  deletes?
            changelist = [
                {
                    "action": "insert",
                    "key": entry.key,
                    "value": entry.value,
                }
                for entry in offer_store.inclusions
            ]
            # TODO: am i reaching too far down here?  can't use DataLayer.batch_update()
            #       since it publishes to chain.
            new_root_hash = await self.service.data_store.insert_batch(
                tree_id=offer_store.store_id,
                changelist=changelist,
            )
            if new_root_hash is None:
                raise Exception("only inserts are supported so a None root hash should not be possible")
            our_store_roots[offer_store.store_id] = new_root_hash

            proofs: List[Proof] = []
            for entry in offer_store.inclusions:
                # TODO: am i reaching too far down here?
                node = await self.service.data_store.get_node_by_key(
                    tree_id=offer_store.store_id, key=entry.key, root_hash=new_root_hash
                )
                # TODO: gets nothing, maybe because the ancestors are not calculated
                #       yet due to waiting for non-pending state?  maybe?
                #       (see: 840910390980427)
                proof_of_inclusion = await self.service.data_store.get_proof_of_inclusion_by_hash(
                    node_hash=node.hash,
                    tree_id=offer_store.store_id,
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
            our_store_proofs.append(store_proof)

        # TODO: make the -1/1 not just misc literals
        # proofs_of_inclusion = {
        #     offer_store.store_id.hex(): (number, offer_store.inclusions)
        #     for offer_stores, number in [[request.offer.maker, -1], [request.offer.taker, 1]]
        #     for offer_store in offer_stores
        #     # **{offer_store.store_id.hex(): -1 for offer_store in request.offer.maker},
        #     # **{offer_store.store_id.hex(): 1 for offer_store in request.offer.taker},
        # }
        all_store_proofs: List[StoreProofs] = [*request.offer.maker, *our_store_proofs]
        proofs_of_inclusion: List[Tuple[str, str, List[str]]] = []
        for store_proofs in all_store_proofs:
            for proof in store_proofs.proofs:
                proof_of_inclusion = ProofOfInclusion(node_hash=proof.node_hash, layers=[])
                sibling_sides_integer = proof_of_inclusion.sibling_sides_integer()
                proofs_of_inclusion.append(
                    (
                        store_proofs.store_id.hex(),
                        # "0x"
                        # + sibling_sides_integer.to_bytes(
                        #     length=sibling_sides_integer.bit_length() // 8, byteorder="big", signed=True
                        # ).hex(),
                        str(sibling_sides_integer),
                        # [sibling_hash.hex() for sibling_hash in proof_of_inclusion.sibling_hashes()],
                        ["0x" + sibling_hash.hex() for sibling_hash in proof_of_inclusion.sibling_hashes()],
                    )
                )
        # proofs_of_inclusion = [
        #     [store_proofs.store_id.hex(), 1, 1]
        #     for store_proofs in all_store_proofs
        #     for proof in store_proofs.proofs
        # ]

        solver: Dict[str, Any] = {
            "proofs_of_inclusion": proofs_of_inclusion,
            **{
                our_offer_store.store_id.hex(): {
                    "new_root": "0x" + our_store_roots[our_offer_store.store_id].hex(),
                    "dependencies": [
                        {
                            # TODO: required 0x :[
                            "launcher_id": "0x" + their_offer_store.store_id.hex(),
                            "values_to_prove": ["0x" + entry.node_hash.hex() for entry in their_offer_store.proofs],
                        }
                        for their_offer_store in request.offer.maker
                    ],
                }
                for our_offer_store in request.offer.taker
            },
        }

        trade_record = await self.service.wallet_rpc.take_offer(
            offer=TradingOffer.from_bytes(request.offer.offer),
            solver=solver,
            # TODO: actually handle fee
            fee=uint64(0),
        )

        # TODO: get access to the transaction id
        return TakeOfferResponse(success=True, transaction_id=trade_record.trade_id)
