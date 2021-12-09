from typing import Any, Callable, Dict


from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_types import Side

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes

# todo input assertions for all rpc's


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
            "/create_kv_store": self.create_kv_store,
            "/update_kv_store": self.update_kv_store,
            "/get_value": self.get_value,
            "/get_pairs": self.get_pairs,
        }

    async def create_kv_store(self, request: Dict[str, Any] = None) -> Dict[str, Any]:
        value = await self.service.create_store()
        return {"id": value.hex()}

    async def get_value(self, request: Dict[str, Any]) -> Dict[str, Any]:
        store_id = bytes32.from_hexstr(request["id"])
        key = hexstr_to_bytes(request["key"])
        value = await self.service.get_value(store_id=store_id, key=key)
        return {"data": value.hex()}

    async def get_pairs(self, request: Dict[str, Any]) -> Dict[str, Any]:
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        value = await self.service.get_pairs(store_id)
        # TODO: fix
        return {"data": value.hex()}  # type: ignore[attr-defined]

    async def get_ancestors(self, request: Dict[str, Any]) -> Dict[str, Any]:
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        key = hexstr_to_bytes(request["key"])
        # TODO: fix
        value = await self.service.get_ancestors(key, store_id)  # type:ignore[arg-type]
        # TODO: fix
        return {"data": value.hex()}  # type: ignore[attr-defined]

    async def update_kv_store(self, request: Dict[str, Any]):
        """
        rows_to_add a list of clvm objects as bytes to add to talbe
        rows_to_remove a list of row hashes to remove
        """
        changelist = [process_change(change) for change in request["changelist"]]
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        # todo input checks
        await self.service.insert(store_id, changelist)
