import dataclasses
from typing import Any, Callable, Dict, Optional


from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_types import Side

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes

# todo input assertions for all rpc's
from chia.util.streamable import recurse_jsonify


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


class DataLayerRpcApi:
    # TODO: other RPC APIs do not accept a wallet and the service start does not expect to provide one
    def __init__(self, data_layer: DataLayer):  # , wallet: DataLayerWallet):
        self.service: DataLayer = data_layer
        # self.data_layer_wallet = wallet
        self.service_name = "chia_data_layer"

    def get_routes(self) -> Dict[str, Callable[[Any], Any]]:
        return {
            "/create_data_store": self.create_data_store,
            "/batch_update": self.batch_update,
            "/get_value": self.get_value,
            "/get_keys_values": self.get_keys_values,
            "/get_ancestors": self.get_ancestors,
            "/get_root": self.get_root,
            "/get_roots": self.get_roots,
            "/delete_key": self.delete_key,
            "/insert": self.insert,
        }

    async def create_data_store(self, request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self.service is None:
            raise Exception("Data layer not created")
        txs, value = await self.service.create_store()
        return {"txs": txs, "id": value.hex()}

    async def get_value(self, request: Dict[str, Any]) -> Dict[str, Any]:
        store_id = bytes32.from_hexstr(request["id"])
        key = hexstr_to_bytes(request["key"])
        if self.service is None:
            raise Exception("Data layer not created")
        value = await self.service.get_value(store_id=store_id, key=key)
        hex = None
        if value is not None:
            hex = value.hex()
        return {"value": hex}

    async def get_keys_values(self, request: Dict[str, Any]) -> Dict[str, Any]:
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        if self.service is None:
            raise Exception("Data layer not created")
        res = await self.service.get_keys_values(store_id)
        json_nodes = []
        for node in res:
            json = recurse_jsonify(dataclasses.asdict(node))  # type: ignore[no-untyped-call]
            json_nodes.append(json)
        return {"keys_values": json_nodes}

    async def get_ancestors(self, request: Dict[str, Any]) -> Dict[str, Any]:
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        node_hash = bytes32.from_hexstr(request["hash"])
        if self.service is None:
            raise Exception("Data layer not created")
        value = await self.service.get_ancestors(node_hash, store_id)
        return {"ancestors": value}

    async def batch_update(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        rows_to_add a list of clvm objects as bytes to add to talbe
        rows_to_remove a list of row hashes to remove
        """
        changelist = [process_change(change) for change in request["changelist"]]
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        transaction_record = await self.service.batch_update(store_id, changelist)
        if transaction_record is None:
            raise Exception(f"Batch update failed for: {store_id}")
        return {"tx_id": transaction_record.name}

    async def insert(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        rows_to_add a list of clvm objects as bytes to add to talbe
        rows_to_remove a list of row hashes to remove
        """
        key = hexstr_to_bytes(request["key"])
        value = hexstr_to_bytes(request["value"])
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        transaction_record = await self.service.batch_update(store_id, changelist)
        return {"tx_id": transaction_record.name}

    async def delete_key(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        rows_to_add a list of clvm objects as bytes to add to talbe
        rows_to_remove a list of row hashes to remove
        """
        key = hexstr_to_bytes(request["key"])
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        changelist = [{"action": "delete", "key": key.hex()}]
        transaction_record = await self.service.batch_update(store_id, changelist)
        return {"tx_id": transaction_record.name}

    async def get_root(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        rows_to_add a list of clvm objects as bytes to add to talbe
        rows_to_remove a list of row hashes to remove
        """
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        res = await self.service.get_root(store_id)
        return {"hash": res}

    async def get_roots(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        rows_to_add a list of clvm objects as bytes to add to talbe
        rows_to_remove a list of row hashes to remove
        """
        store_ids = request["ids"]
        # todo input checks
        if self.service is None:
            raise Exception("Data layer not created")
        res = await self.service.get_roots(store_ids)
        return {"hashes": res}
