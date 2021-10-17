from typing import Any, Callable, Dict


from chia.data_layer.data_layer import DataLayer

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32

# todo input assertions for all rpc's


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
        }

    async def create_kv_store(self, request: Dict[str, Any] = None) -> Dict[str, Any]:
        value = await self.service.create_store()
        return {"id": value}

    async def get_value(self, request: Dict[str, Any]) -> Dict[str, Any]:
        store_id = bytes32(bytes(request["id"]))
        key = Program.from_bytes(bytes(request["key"]))
        value = await self.service.data_store.get_node_by_key(key, tree_id=store_id)
        return {"data": value}

    async def update_kv_store(self, request: Dict[str, Any]):
        """
        rows_to_add a list of clvmobjects as bytes to add to talbe
        rows_to_remove a list of row hashes to remove
        """
        changelist = request["changelist"]

        store_id = bytes32(request["id"])
        # todo input checks
        await self.service.insert(store_id, changelist)
