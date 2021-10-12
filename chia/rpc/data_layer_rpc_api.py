from typing import Any, Callable, Dict


from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_types import Side

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes

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

    async def create_kv_store(self, request: Dict[str, Any]) -> None:
        store_id = bytes32(bytes.fromhex(request["id"]))  # this should be an index we keep
        await self.service.data_store.create_tree(store_id)

    async def get_value(self, request: Dict[str, Any]) -> Dict[str, Any]:
        hash_bytes = bytes32(hexstr_to_bytes(request["key"]))
        store_id = bytes32(hexstr_to_bytes(request["id"]))
        value = await self.service.data_store.get_node_by_key(hash_bytes, tree_id=store_id)
        return {"data": value}

    async def update_kv_store(self, request: Dict[str, Any]):
        """
        rows_to_add a list of clvmobjects as bytes to add to talbe
        rows_to_remove a list of row hashes to remove
        """
        changelist = request["changelist"]
        # todo input checks
        for change in changelist:
            if change["action"] == "insert":
                key = Program.from_bytes(change["key"])
                value = Program.from_bytes(change["value"])
                reference_node_hash = Program.from_bytes(change["reference_node_hash"])
                tree_id = bytes32(change["tree_id"])
                side = Side(change["side"])
                await self.service.data_store.insert(key, value, tree_id, reference_node_hash, side)
            else:
                assert change["action"] == "delete"
                key = Program.from_bytes(change["key"])
                tree_id = bytes32(change["tree_id"])  # todo one changelist for multiple singletons ?
                await self.service.data_store.delete(key, tree_id)

        # TODO: commented out until we identify how to get the wallet available here
        # state = await self.service.data_store.get_table_state(table)

        # todo get changelist hash, order changelist before committing hash
        # TODO: commented out until we identify how to get the wallet available here
        # await self.data_layer_wallet.uptate_table_state(table, state, std_hash(action_list))
        # todo need to mark data as pending and change once tx is confirmed
