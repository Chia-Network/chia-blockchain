from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from typing_extensions import final

from chia.data_layer.data_layer_errors import OfferIntegrityError
from chia.data_layer.data_layer_util import ProofOfInclusion, ProofOfInclusionLayer, Side, Subscription, leaf_hash
from chia.data_layer.data_layer_wallet import DataLayerWallet, Mirror
from chia.rpc.data_layer_rpc_util import marshal
from chia.rpc.rpc_server import Endpoint, EndpointResult
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes

# todo input assertions for all rpc's
from chia.util.ints import uint64
from chia.util.streamable import recurse_jsonify
from chia.wallet.trading.offer import Offer as TradingOffer

if TYPE_CHECKING:
    from chia.data_layer.data_layer import DataLayer


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


@dataclasses.dataclass(frozen=True)
class Layer:
    # This class is similar to chia.data_layer.data_layer_util.ProofOfInclusionLayer
    # but is being retained for now to keep the API schema definition localized here.

    other_hash_side: Side
    other_hash: bytes32
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
    fee: uint64

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> MakeOfferRequest:
        return cls(
            maker=tuple(OfferStore.unmarshal(offer_store) for offer_store in marshalled["maker"]),
            taker=tuple(OfferStore.unmarshal(offer_store) for offer_store in marshalled["taker"]),
            fee=uint64(marshalled["fee"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "maker": [offer_store.marshal() for offer_store in self.maker],
            "taker": [offer_store.marshal() for offer_store in self.taker],
            "fee": int(self.fee),
        }


@dataclasses.dataclass(frozen=True)
class Proof:
    key: bytes
    value: bytes
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
    fee: uint64

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> TakeOfferRequest:
        return cls(offer=Offer.unmarshal(marshalled["offer"]), fee=uint64(marshalled["fee"]))

    def marshal(self) -> Dict[str, Any]:
        return {
            "offer": self.offer.marshal(),
            "fee": int(self.fee),
        }


@dataclasses.dataclass(frozen=True)
class TakeOfferResponse:
    success: bool
    trade_id: bytes32

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> TakeOfferResponse:
        return cls(
            success=marshalled["success"],
            trade_id=bytes32.from_hexstr(marshalled["trade_id"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "trade_id": self.trade_id.hex(),
        }


@final
@dataclasses.dataclass(frozen=True)
class VerifyOfferResponse:
    success: bool
    valid: bool
    error: Optional[str] = None
    fee: Optional[uint64] = None

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> VerifyOfferResponse:
        raw_fee = marshalled["fee"]
        if raw_fee is None:
            fee = None
        else:
            fee = uint64(raw_fee)

        return cls(
            success=marshalled["success"],
            valid=marshalled["valid"],
            error=marshalled["error"],
            fee=fee,
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "valid": self.valid,
            "error": self.error,
            "fee": None if self.fee is None else int(self.fee),
        }


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


def verify_offer(
    maker: Tuple[StoreProofs, ...],
    taker: Tuple[OfferStore, ...],
    summary: Dict[str, Any],
) -> None:
    # TODO: consistency in error messages
    # TODO: custom exceptions
    # TODO: show data in errors?
    # TODO: collect and report all failures
    # TODO: review for case coverage (and test those cases)

    if len({store_proof.store_id for store_proof in maker}) != len(maker):
        raise OfferIntegrityError("maker: repeated store id")

    for store_proof in maker:
        proofs: List[ProofOfInclusion] = []
        for reference_proof in store_proof.proofs:
            proof = ProofOfInclusion(
                node_hash=reference_proof.node_hash,
                layers=[
                    ProofOfInclusionLayer(
                        other_hash_side=layer.other_hash_side,
                        other_hash=layer.other_hash,
                        combined_hash=layer.combined_hash,
                    )
                    for layer in reference_proof.layers
                ],
            )

            proofs.append(proof)

            if leaf_hash(key=reference_proof.key, value=reference_proof.value) != proof.node_hash:
                raise OfferIntegrityError("maker: node hash does not match key and value")

            if not proof.valid():
                raise OfferIntegrityError("maker: invalid proof of inclusion found")

        # TODO: verify each kv hash to the proof's node hash
        roots = {proof.root_hash for proof in proofs}
        if len(roots) > 1:
            raise OfferIntegrityError("maker: multiple roots referenced for a single store id")
        if len(roots) < 1:
            raise OfferIntegrityError("maker: no roots referenced for store id")

    # TODO: what about validating duplicate entries are consistent?
    maker_from_offer = {
        bytes32.from_hexstr(offered["launcher_id"]): bytes32.from_hexstr(offered["new_root"])
        for offered in summary["offered"]
    }

    maker_from_reference = {
        # verified above that there is at least one proof and all combined hashes match
        store_proof.store_id: store_proof.proofs[0].layers[-1].combined_hash
        for store_proof in maker
    }

    if maker_from_offer != maker_from_reference:
        raise OfferIntegrityError("maker: offered stores and their roots do not match the reference data")

    taker_from_offer = {
        bytes32.from_hexstr(dependency["launcher_id"]): [
            bytes32.from_hexstr(value) for value in dependency["values_to_prove"]
        ]
        for offered in summary["offered"]
        for dependency in offered["dependencies"]
    }

    taker_from_reference = {
        store.store_id: [leaf_hash(key=inclusion.key, value=inclusion.value) for inclusion in store.inclusions]
        for store in taker
    }

    if taker_from_offer != taker_from_reference:
        raise OfferIntegrityError("taker: reference and offer inclusions do not match")


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
            "/add_mirror": self.add_mirror,
            "/delete_mirror": self.delete_mirror,
            "/get_mirrors": self.get_mirrors,
            "/remove_subscriptions": self.remove_subscriptions,
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
        urls = request.get("urls", [])
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

    async def remove_subscriptions(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        store_id = request.get("id")
        if store_id is None:
            raise Exception("missing store id in request")
        store_id_bytes = bytes32.from_hexstr(store_id)
        urls = request["urls"]
        await self.service.remove_subscriptions(store_id=store_id_bytes, urls=urls)
        return {}

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

    async def add_mirror(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = request["id"]
        id_bytes = bytes32.from_hexstr(store_id)
        urls = request["urls"]
        amount = request["amount"]
        fee = get_fee(self.service.config, request)
        await self.service.add_mirror(id_bytes, urls, amount, fee)
        return {}

    async def delete_mirror(self, request: Dict[str, Any]) -> EndpointResult:
        coin_id = request["id"]
        id_bytes = bytes32.from_hexstr(coin_id)
        fee = get_fee(self.service.config, request)
        await self.service.delete_mirror(id_bytes, fee)
        return {}

    async def get_mirrors(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = request["id"]
        id_bytes = bytes32.from_hexstr(store_id)
        mirrors: List[Mirror] = await self.service.get_mirrors(id_bytes)
        return {"mirrors": [mirror.to_json_dict() for mirror in mirrors]}

    @marshal()  # type: ignore[arg-type]
    async def make_offer(self, request: MakeOfferRequest) -> MakeOfferResponse:
        fee = get_fee(self.service.config, {"fee": request.fee})
        offer = await self.service.make_offer(maker=request.maker, taker=request.taker, fee=fee)
        return MakeOfferResponse(success=True, offer=offer)

    @marshal()  # type: ignore[arg-type]
    async def take_offer(self, request: TakeOfferRequest) -> TakeOfferResponse:
        fee = get_fee(self.service.config, {"fee": request.fee})
        trade_record = await self.service.take_offer(
            offer_bytes=request.offer.offer,
            maker=request.offer.maker,
            taker=request.offer.taker,
            fee=fee,
        )
        return TakeOfferResponse(success=True, trade_id=trade_record.trade_id)

    @marshal()  # type: ignore[arg-type]
    async def verify_offer(self, request: TakeOfferRequest) -> VerifyOfferResponse:
        fee = get_fee(self.service.config, {"fee": request.fee})

        offer = TradingOffer.from_bytes(request.offer.offer)
        summary = await DataLayerWallet.get_offer_summary(offer=offer)

        try:
            verify_offer(maker=request.offer.maker, taker=request.offer.taker, summary=summary)
        except OfferIntegrityError as e:
            return VerifyOfferResponse(success=True, valid=False, error=str(e))

        return VerifyOfferResponse(success=True, valid=True, fee=fee)
