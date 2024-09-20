from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from chia.data_layer.data_layer_errors import OfferIntegrityError
from chia.data_layer.data_layer_util import (
    CancelOfferRequest,
    CancelOfferResponse,
    ClearPendingRootsRequest,
    ClearPendingRootsResponse,
    DLProof,
    GetProofRequest,
    GetProofResponse,
    HashOnlyProof,
    MakeOfferRequest,
    MakeOfferResponse,
    ProofLayer,
    Side,
    StoreProofsHashes,
    Subscription,
    TakeOfferRequest,
    TakeOfferResponse,
    Unspecified,
    VerifyOfferResponse,
    VerifyProofResponse,
    unspecified,
)
from chia.data_layer.data_layer_wallet import DataLayerWallet, Mirror, verify_offer
from chia.rpc.data_layer_rpc_util import marshal
from chia.rpc.rpc_server import Endpoint, EndpointResult
from chia.rpc.util import marshal as streamable_marshal
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes

# todo input assertions for all rpc's
from chia.util.ints import uint8, uint64
from chia.util.streamable import recurse_jsonify
from chia.util.ws_message import WsRpcMessage
from chia.wallet.trading.offer import Offer as TradingOffer

if TYPE_CHECKING:
    from chia.data_layer.data_layer import DataLayer


def process_change(change: Dict[str, Any]) -> Dict[str, Any]:
    # TODO: A full class would likely be nice for this so downstream doesn't
    #       have to deal with maybe-present attributes or Dict[str, Any] hints.
    reference_node_hash = change.get("reference_node_hash")
    if reference_node_hash is not None:
        reference_node_hash = bytes32.from_hexstr(reference_node_hash)

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


def process_change_multistore(update: Dict[str, Any]) -> Dict[str, Any]:
    store_id = update.get("store_id")
    if store_id is None:
        raise Exception("Each update must specify a store_id")
    changelist = update.get("changelist")
    if changelist is None:
        raise Exception("Each update must specify a changelist")
    res: Dict[str, Any] = {}
    res["store_id"] = bytes32.from_hexstr(store_id)
    res["changelist"] = [process_change(change) for change in changelist]
    return res


def get_fee(config: Dict[str, Any], request: Dict[str, Any]) -> uint64:
    fee = request.get("fee")
    if fee is None:
        fee = 0  # DL no longer reads the fee from the config
    return uint64(fee)


class DataLayerRpcApi:
    # TODO: other RPC APIs do not accept a wallet and the service start does not expect to provide one
    def __init__(self, data_layer: DataLayer):  # , wallet: DataLayerWallet):
        self.service: DataLayer = data_layer
        self.service_name = "chia_data_layer"

    def get_routes(self) -> Dict[str, Endpoint]:
        return {
            "/wallet_log_in": self.wallet_log_in,
            "/create_data_store": self.create_data_store,
            "/get_owned_stores": self.get_owned_stores,
            "/batch_update": self.batch_update,
            "/multistore_batch_update": self.multistore_batch_update,
            "/submit_pending_root": self.submit_pending_root,
            "/submit_all_pending_roots": self.submit_all_pending_roots,
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
            "/verify_offer": self.verify_offer,
            "/cancel_offer": self.cancel_offer,
            "/get_sync_status": self.get_sync_status,
            "/check_plugins": self.check_plugins,
            "/clear_pending_roots": self.clear_pending_roots,
            "/get_proof": self.get_proof,
            "/verify_proof": self.verify_proof,
        }

    async def _state_changed(self, change: str, change_data: Optional[Dict[str, Any]]) -> List[WsRpcMessage]:
        return []

    async def wallet_log_in(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        fingerprint = cast(int, request["fingerprint"])
        await self.service.wallet_log_in(fingerprint=fingerprint)
        return {}

    async def create_data_store(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        fee = get_fee(self.service.config, request)
        verbose = request.get("verbose", False)
        txs, value = await self.service.create_store(uint64(fee))
        if verbose:
            return {"txs": txs, "id": value.hex()}
        else:
            return {"id": value.hex()}

    async def get_owned_stores(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        singleton_records = await self.service.get_owned_stores()
        return {"store_ids": [singleton.launcher_id.hex() for singleton in singleton_records]}

    async def get_value(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = bytes32.from_hexstr(request["id"])
        key = hexstr_to_bytes(request["key"])
        # NOTE: being outside the rpc, this retains the none-means-unspecified semantics
        root_hash: Optional[str] = request.get("root_hash")
        resolved_root_hash: Union[bytes32, Unspecified]
        if root_hash is not None:
            resolved_root_hash = bytes32.from_hexstr(root_hash)
        else:
            resolved_root_hash = unspecified
        if self.service is None:
            raise Exception("Data layer not created")
        value = await self.service.get_value(store_id=store_id, key=key, root_hash=resolved_root_hash)
        hex = None
        if value is not None:
            hex = value.hex()
        return {"value": hex}

    async def get_keys(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = bytes32.from_hexstr(request["id"])
        # NOTE: being outside the rpc, this retains the none-means-unspecified semantics
        root_hash: Optional[str] = request.get("root_hash")
        page = request.get("page", None)
        max_page_size = request.get("max_page_size", None)
        resolved_root_hash: Union[bytes32, Unspecified]
        if root_hash is not None:
            resolved_root_hash = bytes32.from_hexstr(root_hash)
        else:
            resolved_root_hash = unspecified
        if self.service is None:
            raise Exception("Data layer not created")

        if page is None:
            keys = await self.service.get_keys(store_id, resolved_root_hash)
        else:
            keys_paginated = await self.service.get_keys_paginated(store_id, resolved_root_hash, page, max_page_size)
            keys = keys_paginated.keys

        # NOTE: here we do support zeros as the empty root
        if keys == [] and resolved_root_hash is not unspecified and resolved_root_hash != bytes32([0] * 32):
            raise Exception(f"Can't find keys for {resolved_root_hash}")

        response: EndpointResult = {"keys": [f"0x{key.hex()}" for key in keys]}

        if page is not None:
            response.update(
                {
                    "total_pages": keys_paginated.total_pages,
                    "total_bytes": keys_paginated.total_bytes,
                    "root_hash": keys_paginated.root_hash,
                },
            )

        return response

    async def get_keys_values(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = bytes32.from_hexstr(request["id"])
        # NOTE: being outside the rpc, this retains the none-means-unspecified semantics
        root_hash: Optional[str] = request.get("root_hash")
        page = request.get("page", None)
        max_page_size = request.get("max_page_size", None)
        resolved_root_hash: Union[bytes32, Unspecified]
        if root_hash is not None:
            resolved_root_hash = bytes32.from_hexstr(root_hash)
        else:
            resolved_root_hash = unspecified
        if self.service is None:
            raise Exception("Data layer not created")

        if page is None:
            keys_values = await self.service.get_keys_values(store_id, resolved_root_hash)
        else:
            keys_values_paginated = await self.service.get_keys_values_paginated(
                store_id, resolved_root_hash, page, max_page_size
            )
            keys_values = keys_values_paginated.keys_values

        json_nodes = [recurse_jsonify(dataclasses.asdict(node)) for node in keys_values]
        # NOTE: here we do support zeros as the empty root
        if not json_nodes and resolved_root_hash is not unspecified and resolved_root_hash != bytes32([0] * 32):
            raise Exception(f"Can't find keys and values for {resolved_root_hash}")

        response: EndpointResult = {"keys_values": json_nodes}

        if page is not None:
            response.update(
                {
                    "total_pages": keys_values_paginated.total_pages,
                    "total_bytes": keys_values_paginated.total_bytes,
                    "root_hash": keys_values_paginated.root_hash,
                },
            )

        return response

    async def get_ancestors(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = bytes32.from_hexstr(request["id"])
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
        store_id = bytes32.from_hexstr(request["id"])
        submit_on_chain = request.get("submit_on_chain", True)
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        transaction_record = await self.service.batch_update(store_id, changelist, uint64(fee), submit_on_chain)
        if submit_on_chain:
            if transaction_record is None:
                raise Exception(f"Batch update failed for: {store_id}")
            return {"tx_id": transaction_record.name}
        else:
            if transaction_record is not None:
                raise Exception("Transaction submitted on chain, but submit_on_chain set to False")
            return {}

    async def multistore_batch_update(self, request: Dict[str, Any]) -> EndpointResult:
        fee = get_fee(self.service.config, request)
        store_updates = [process_change_multistore(update) for update in request["store_updates"]]
        submit_on_chain = request.get("submit_on_chain", True)
        if self.service is None:
            raise Exception("Data layer not created")
        transaction_records = await self.service.multistore_batch_update(store_updates, uint64(fee), submit_on_chain)
        if submit_on_chain:
            if transaction_records == []:
                raise Exception("Batch update failed")
            return {"tx_id": [transaction_record.name for transaction_record in transaction_records]}
        else:
            if transaction_records != []:
                raise Exception("Transaction submitted on chain, but submit_on_chain set to False")
            return {}

    async def submit_pending_root(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = bytes32.from_hexstr(request["id"])
        fee = get_fee(self.service.config, request)
        transaction_record = await self.service.submit_pending_root(store_id, uint64(fee))
        return {"tx_id": transaction_record.name}

    async def submit_all_pending_roots(self, request: Dict[str, Any]) -> EndpointResult:
        fee = get_fee(self.service.config, request)
        transaction_records = await self.service.submit_all_pending_roots(uint64(fee))
        return {"tx_id": [transaction_record.name for transaction_record in transaction_records]}

    async def insert(self, request: Dict[str, Any]) -> EndpointResult:
        """
        rows_to_add a list of clvm objects as bytes to add to table
        rows_to_remove a list of row hashes to remove
        """
        fee = get_fee(self.service.config, request)
        key = hexstr_to_bytes(request["key"])
        value = hexstr_to_bytes(request["value"])
        store_id = bytes32.from_hexstr(request["id"])
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        changelist = [{"action": "insert", "key": key, "value": value}]
        transaction_record = await self.service.batch_update(store_id, changelist, uint64(fee))
        assert transaction_record is not None
        return {"tx_id": transaction_record.name}

    async def delete_key(self, request: Dict[str, Any]) -> EndpointResult:
        """
        rows_to_add a list of clvm objects as bytes to add to table
        rows_to_remove a list of row hashes to remove
        """
        fee = get_fee(self.service.config, request)
        key = hexstr_to_bytes(request["key"])
        store_id = bytes32.from_hexstr(request["id"])
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        changelist = [{"action": "delete", "key": key}]
        transaction_record = await self.service.batch_update(store_id, changelist, uint64(fee))
        assert transaction_record is not None
        return {"tx_id": transaction_record.name}

    async def get_root(self, request: Dict[str, Any]) -> EndpointResult:
        """get hash of latest tree root"""
        store_id = bytes32.from_hexstr(request["id"])
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        rec = await self.service.get_root(store_id)
        if rec is None:
            raise Exception(f"Failed to get root for {store_id.hex()}")
        return {"hash": rec.root, "confirmed": rec.confirmed, "timestamp": rec.timestamp}

    async def get_local_root(self, request: Dict[str, Any]) -> EndpointResult:
        """get hash of latest tree root saved in our local datastore"""
        store_id = bytes32.from_hexstr(request["id"])
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
        retain_data = request.get("retain", False)
        if store_id is None:
            raise Exception("missing store id in request")
        if self.service is None:
            raise Exception("Data layer not created")
        store_id_bytes = bytes32.from_hexstr(store_id)
        await self.service.unsubscribe(store_id_bytes, retain_data)
        return {}

    async def subscriptions(self, request: Dict[str, Any]) -> EndpointResult:
        """
        List current subscriptions
        """
        if self.service is None:
            raise Exception("Data layer not created")
        subscriptions: List[Subscription] = await self.service.get_subscriptions()
        return {"store_ids": [sub.store_id.hex() for sub in subscriptions]}

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
            ids_bytes = [subscription.store_id for subscription in subscriptions]
        overwrite = request.get("overwrite", False)
        foldername: Optional[Path] = None
        if "foldername" in request:
            foldername = Path(request["foldername"])
        for store_id in ids_bytes:
            await self.service.add_missing_files(store_id, overwrite, foldername)
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
        page = request.get("page", None)
        max_page_size = request.get("max_page_size", None)
        res: List[Dict[str, Any]] = []

        if page is None:
            records_dict = await self.service.get_kv_diff(id_bytes, hash_1_bytes, hash_2_bytes)
            records = list(records_dict)
        else:
            kv_diff_paginated = await self.service.get_kv_diff_paginated(
                id_bytes, hash_1_bytes, hash_2_bytes, page, max_page_size
            )
            records = kv_diff_paginated.kv_diff

        for rec in records:
            res.append({"type": rec.type.name, "key": rec.key.hex(), "value": rec.value.hex()})

        response: EndpointResult = {"diff": res}
        if page is not None:
            response.update(
                {
                    "total_pages": kv_diff_paginated.total_pages,
                    "total_bytes": kv_diff_paginated.total_bytes,
                },
            )

        return response

    async def add_mirror(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = request["id"]
        id_bytes = bytes32.from_hexstr(store_id)
        urls = request["urls"]
        amount = request["amount"]
        fee = get_fee(self.service.config, request)
        await self.service.add_mirror(id_bytes, urls, amount, fee)
        return {}

    async def delete_mirror(self, request: Dict[str, Any]) -> EndpointResult:
        coin_id = request["coin_id"]
        coin_id_bytes = bytes32.from_hexstr(coin_id)
        fee = get_fee(self.service.config, request)
        await self.service.delete_mirror(coin_id_bytes, fee)
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

    @marshal()  # type: ignore[arg-type]
    async def cancel_offer(self, request: CancelOfferRequest) -> CancelOfferResponse:
        fee = get_fee(self.service.config, {"fee": request.fee})

        await self.service.cancel_offer(
            trade_id=request.trade_id,
            secure=request.secure,
            fee=fee,
        )

        return CancelOfferResponse(success=True)

    async def get_sync_status(self, request: Dict[str, Any]) -> EndpointResult:
        store_id = request["id"]
        id_bytes = bytes32.from_hexstr(store_id)
        if self.service is None:
            raise Exception("Data layer not created")
        sync_status = await self.service.get_sync_status(id_bytes)

        return {
            "sync_status": {
                "root_hash": sync_status.root_hash.hex(),
                "generation": sync_status.generation,
                "target_root_hash": sync_status.target_root_hash.hex(),
                "target_generation": sync_status.target_generation,
            }
        }

    async def check_plugins(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        plugin_status = await self.service.check_plugins()

        return plugin_status.marshal()

    @marshal()  # type: ignore[arg-type]
    async def clear_pending_roots(self, request: ClearPendingRootsRequest) -> ClearPendingRootsResponse:
        root = await self.service.data_store.clear_pending_roots(store_id=request.store_id)

        return ClearPendingRootsResponse(success=root is not None, root=root)

    @streamable_marshal
    async def get_proof(self, request: GetProofRequest) -> GetProofResponse:
        root = await self.service.get_root(store_id=request.store_id)
        if root is None:
            raise ValueError("no root")

        all_proofs: List[HashOnlyProof] = []
        for key in request.keys:
            node = await self.service.data_store.get_node_by_key(store_id=request.store_id, key=key)
            pi = await self.service.data_store.get_proof_of_inclusion_by_hash(
                store_id=request.store_id, node_hash=node.hash, use_optimized=True
            )

            proof = HashOnlyProof.from_key_value(
                key=key,
                value=node.value,
                node_hash=pi.node_hash,
                layers=[
                    ProofLayer(
                        other_hash_side=uint8(layer.other_hash_side),
                        other_hash=layer.other_hash,
                        combined_hash=layer.combined_hash,
                    )
                    for layer in pi.layers
                ],
            )
            all_proofs.append(proof)

        store_proof = StoreProofsHashes(store_id=request.store_id, proofs=all_proofs)
        return GetProofResponse(
            proof=DLProof(
                store_proofs=store_proof,
                coin_id=root.coin_id,
                inner_puzzle_hash=root.inner_puzzle_hash,
            ),
            success=True,
        )

    @streamable_marshal
    async def verify_proof(self, request: DLProof) -> VerifyProofResponse:
        response = await self.service.wallet_rpc.dl_verify_proof(request)
        return response
