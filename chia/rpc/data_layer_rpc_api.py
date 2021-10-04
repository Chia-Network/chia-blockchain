from typing import Any, Callable, Dict, List

from chia.data_layer.data_layer import DataLayer

# from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.data_layer.data_store import Action, OperationType
from chia.types.blockchain_format.program import SerializedProgram
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
        return {"/create_table": self.create_table, "/update_table": self.update_table, "/get_row": self.get_row}

    async def create_table(self, request: Dict[str, Any]) -> None:
        table_bytes = bytes32(bytes.fromhex(request["table"]))
        name = request["name"]
        await self.service.data_store.create_table(id=table_bytes, name=name)

    async def get_row(self, request: Dict[str, Any]) -> Dict[str, Any]:
        hash_bytes = bytes32(hexstr_to_bytes(request["row_hash"]))
        table_bytes = bytes32(hexstr_to_bytes(request["table"]))
        table_row = await self.service.data_store.get_row_by_hash(table=table_bytes, row_hash=hash_bytes)
        return {"row_data": table_row.bytes.hex(), "row_hash": table_row.hash.hex()}

    async def update_table(self, request: Dict[str, Any]) -> Dict:
        """
        rows_to_add a list of serialized programs as hex strings to add to table
        rows_to_remove a list of row hashes to remove
        """
        table: bytes32 = bytes32(hexstr_to_bytes(request["table"]))
        changelist = request["changelist"]
        action_list: List[Action] = []
        for change in changelist:
            if change["action"] == "insert":
                serialized_program = SerializedProgram.fromhex(hexstr=change["row_data"])
                table_row = await self.service.data_store.insert_row(table=table, serialized_program=serialized_program)
                operation = OperationType.INSERT
            else:
                assert change["action"] == "delete"
                row_hash = bytes32(hexstr_to_bytes(change["row_hash"]))
                table_row = await self.service.data_store.delete_row_by_hash(table, row_hash)
                operation = OperationType.DELETE
            action_list.append(Action(op=operation, row=table_row))

        changelist = []

        for action in action_list:
            changelist.append({"action": "insert", "row_data": action.row.bytes, "row_hash": action.row.hash})

        return {"changelist": changelist}

        # TODO: commented out until we identify how to get the wallet available here
        # state = await self.service.data_store.get_table_state(table)

        # todo get changelist hash, order changelist before committing hash
        # TODO: commented out until we identify how to get the wallet available here
        # await self.data_layer_wallet.uptate_table_state(table, state, std_hash(action_list))
        # todo need to mark data as pending and change once tx is confirmed
