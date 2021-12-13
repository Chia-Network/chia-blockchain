import asyncio
import aiosqlite
from aiohttp import web
from chia.data_layer.data_store import DataStore
from chia.util.db_wrapper import DBWrapper
from chia.types.blockchain_format.tree_hash import bytes32
from tests.core.data_layer.util import add_01234567_example


class DataLayerServer:
    async def handle_tree_root(self, request):
        tree_id = request.rel_url.query["tree_id"]
        tree_id_bytes = bytes32.from_hexstr(tree_id)
        tree_root = await self.data_store.get_tree_root(tree_id_bytes)
        result = {
            "tree_id": tree_id,
            "generation": tree_root.generation,
            "node_hash": str(tree_root.node_hash),
            "status": tree_root.status.value,
        }
        return web.json_response(result)

    async def handle_tree_nodes(self, request):
        node_hash = request.rel_url.query["node_hash"]
        tree_id = request.rel_url.query["tree_id"]
        node_hash_bytes = bytes32.from_hexstr(node_hash)
        tree_id_bytes = bytes32.from_hexstr(tree_id)
        answer = await self.data_store.answer_server_query(node_hash_bytes, tree_id_bytes)
        return web.json_response({"answer": answer})

    async def init_example_data_store(self):
        tree_id = bytes32(b"\0" * 32)
        await self.data_store.create_tree(tree_id=tree_id)
        await add_01234567_example(data_store=self.data_store, tree_id=tree_id)

    async def start(self):
        self.db_connection = await aiosqlite.connect(":memory:")
        await self.db_connection.execute("PRAGMA foreign_keys = ON")
        self.db_wrapper = DBWrapper(self.db_connection)
        self.data_store = await DataStore.create(db_wrapper=self.db_wrapper)
        await self.init_example_data_store()

        app = web.Application()
        app.add_routes(
            [
                web.get("/get_tree_root", self.handle_tree_root),
                web.get("/get_tree_nodes", self.handle_tree_nodes),
            ]
        )
        return app


if __name__ == "__main__":
    data_layer_server = DataLayerServer()
    web.run_app(data_layer_server.start())
