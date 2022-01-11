import aiosqlite
import aiohttp
import json
from random import Random
from typing import Dict
from aiohttp import web
from chia.data_layer.data_store import DataStore
from chia.util.db_wrapper import DBWrapper
from chia.types.blockchain_format.tree_hash import bytes32
from tests.core.data_layer.util import generate_big_datastore
from chia.data_layer.data_layer_types import TerminalNode, InsertionData
from dataclasses import dataclass


@dataclass
class DataLayerServer:
    async def handle_tree_root(self, request: Dict[str, str]) -> str:
        tree_id = request["tree_id"]
        tree_id_bytes = bytes32.from_hexstr(tree_id)
        tree_root = await self.data_store.get_tree_root(tree_id_bytes)
        if tree_root.node_hash is None:
            return json.dumps({})
        result = {
            "tree_id": tree_id,
            "generation": tree_root.generation,
            "node_hash": tree_root.node_hash.hex(),
            "status": tree_root.status.value,
        }
        return json.dumps(result)

    async def handle_tree_nodes(self, request: Dict[str, str]) -> str:
        node_hash = request["node_hash"]
        tree_id = request["tree_id"]
        root_hash = request["root_hash"]
        node_hash_bytes = bytes32.from_hexstr(node_hash)
        tree_id_bytes = bytes32.from_hexstr(tree_id)
        nodes = await self.data_store.get_left_to_right_ordering(node_hash_bytes, tree_id_bytes)
        answer = []
        for node in nodes:
            if isinstance(node, TerminalNode):
                answer.append(
                    {
                        "key": node.key.hex(),
                        "value": node.value.hex(),
                        "is_terminal": True,
                    }
                )
            else:
                answer.append(
                    {
                        "left": str(node.left_hash),
                        "right": str(node.right_hash),
                        "is_terminal": False,
                    }
                )
        current_tree_root = await self.data_store.get_tree_root(tree_id_bytes)
        root_changed = current_tree_root.node_hash != bytes32.from_hexstr(root_hash)
        return json.dumps(
            {
                "root_changed": root_changed,
                "answer": answer,
            }
        )

    async def handle_operations(self, request: Dict[str, str]) -> str:
        tree_id = request["tree_id"]
        generation = request["generation"]
        tree_id_bytes = bytes32.from_hexstr(tree_id)
        operations_data = await self.data_store.get_operations(tree_id_bytes, int(generation))
        answer = []
        for operation in operations_data:
            if isinstance(operation, InsertionData):
                reference_node_hash = (
                    "None" if operation.reference_node_hash is None else operation.reference_node_hash.hex()
                )
                side = "None" if operation.side is None else operation.side.value
                answer.append(
                    {
                        "is_insert": True,
                        "hash": operation.hash.hex(),
                        "key": operation.key.hex(),
                        "value": operation.value.hex(),
                        "reference_node_hash": reference_node_hash,
                        "side": side,
                        "root_status": operation.root_status.value,
                    }
                )
            else:
                answer.append(
                    {
                        "is_insert": False,
                        "hash": "None" if operation.hash is None else operation.hash.hex(),
                        "key": operation.key.hex(),
                        "root_status": operation.root_status.value,
                    }
                )

        return json.dumps(answer)

    async def init_example_data_store(self) -> None:
        tree_id = bytes32(b"\0" * 32)
        await self.data_store.create_tree(tree_id=tree_id)
        random = Random()
        random.seed(100, version=2)
        await generate_big_datastore(data_store=self.data_store, tree_id=tree_id, random=random)
        print("Generated datastore.")

    async def websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)

        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                json_request = json.loads(msg.data)
                if json_request["type"] == "close":
                    await ws.close()
                    return ws
                elif json_request["type"] == "request_root":
                    json_response = await self.handle_tree_root(json_request)
                elif json_request["type"] == "request_nodes":
                    json_response = await self.handle_tree_nodes(json_request)
                elif json_request["type"] == "request_operations":
                    json_response = await self.handle_operations(json_request)
                await ws.send_str(json_response)

        return ws

    async def start(self) -> web.Application:
        self.db_connection = await aiosqlite.connect(":memory:")
        await self.db_connection.execute("PRAGMA foreign_keys = ON")
        self.db_wrapper = DBWrapper(self.db_connection)
        self.data_store = await DataStore.create(db_wrapper=self.db_wrapper)
        await self.init_example_data_store()

        app = web.Application()
        app.router.add_route("GET", "/ws", self.websocket_handler)
        return app


if __name__ == "__main__":
    data_layer_server = DataLayerServer()
    web.run_app(data_layer_server.start())
