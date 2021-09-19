from typing import Callable, Dict, List
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.data_layer.data_store import Action, OperationType
from chia.types.blockchain_format.sized_bytes import bytes32

# todo input assertions for all rpc's
from chia.util.hash import std_hash


class DataLayerRpcApi:
    def __init__(self, service: DataLayer, wallet: DataLayerWallet):
        self.data_layer_service: DataLayer = service
        self.data_layer_wallet = wallet
        self.service_name = "chia_data_layer"

    def get_routes(self) -> Dict[str, Callable]:
        return {"/update": self.update, "/get_row": self.get_row}

    async def get_row(self, request: Dict) -> bytes:
        row = b""
        if "hash" in request:
            row = await self.data_layer_service.data_store.get_row_by_hash(request["hash"])
        elif "index" in request:
            row = await self.data_layer_service.data_store.get_row_by_index(request["index"])
        return row

    async def update(self, request: Dict):
        """
        rows_to_add a list of clvmobjects as bytes to add to talbe
        rows_to_remove a list of row hashes to remove
        """
        table: bytes32 = request["table"]
        changelist = request["changelist"]
        action_list: List[Action] = []
        for change in changelist:
            if change["action"] == "insert":
                row = change["row"]
                operation = OperationType.INSERT
                index = await self.data_layer_service.data_store.insert_row(table, row)
            else:
                assert change["action"] == "delete"
                row, index = await self.data_layer_service.data_store.delete_row_by_hash(table, change["row"])
                operation = OperationType.DELETE
            action_list.append(Action(op=operation, row=row, row_index=index))
        state = await self.data_layer_service.data_store.get_table_state(table)

        # todo get changelist hash, order changelist before committing hash
        await self.data_layer_wallet.uptate_table_state(table, state, std_hash(action_list))
        # todo need to mark data as pending and change once tx is confirmed
