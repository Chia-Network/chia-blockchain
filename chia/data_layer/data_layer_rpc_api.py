from typing import Any, Callable, Dict, List
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.data_layer.data_store import Action, OperationType
from chia.types.blockchain_format.sized_bytes import bytes32

# todo input assertions for all rpc's
from chia.util.hash import std_hash


class DataLayerRpcApi:
    def __init__(self, data_layer: DataLayer, wallet: DataLayerWallet):
        self.service: DataLayer = data_layer
        self.data_layer_wallet = wallet
        self.service_name = "chia_data_layer"

    def get_routes(self) -> Dict[str, Callable[[Any], Any]]:
        return {"/update": self.update, "/get_row": self.get_row}

    async def get_row(self, request: Dict[str, Any]) -> bytes:
        row = b""
        if "hash" in request:
            table_row = await self.service.data_store.get_row_by_hash(table=b"", row_hash=request["hash"])
            row = table_row.bytes
        elif "index" in request:
            table_row = await self.service.data_store.get_row_by_index(table=b"", index=request["index"])
            row = table_row.bytes
        return row

    async def update(self, request: Dict[str, Any]) -> None:
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
                table_row = await self.service.data_store.insert_row(table, row)
            else:
                assert change["action"] == "delete"
                table_row = await self.service.data_store.delete_row_by_hash(table, change["row"])
                operation = OperationType.DELETE
            action_list.append(Action(op=operation, row=table_row.clvm_object, row_index=table_row.index))
        state = await self.service.data_store.get_table_state(table)

        # todo get changelist hash, order changelist before committing hash
        await self.data_layer_wallet.uptate_table_state(table, state, std_hash(action_list))
        # todo need to mark data as pending and change once tx is confirmed
