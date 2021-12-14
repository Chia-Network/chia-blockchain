import asyncio
import aiosqlite
import aiohttp
from chia.data_layer.data_store import DataStore
from chia.util.db_wrapper import DBWrapper
from chia.types.blockchain_format.tree_hash import bytes32
from chia.types.blockchain_format.program import Program
from chia.util.byte_types import hexstr_to_bytes
from chia.data_layer.data_layer_types import Status, NodeType
from typing import List, Any


class DataLayerClient:
    async def init_db(self) -> None:
        self.db_connection = await aiosqlite.connect(":memory_client:")
        self.db_wrapper = DBWrapper(self.db_connection)
        self.data_store = await DataStore.create(db_wrapper=self.db_wrapper)
        tree_id = bytes32(b"\0" * 32)
        await self.data_store.create_tree(tree_id=tree_id)

    async def download_data_layer(self) -> None:
        await self.init_db()
        async with aiohttp.ClientSession() as session:
            tree_id = "0x0000000000000000000000000000000000000000000000000000000000000000"
            url = f"http://0.0.0.0:8080/get_tree_root?tree_id={tree_id}"
            async with session.get(url) as r:
                root_json = await r.json()
            node = root_json["node_hash"]
            print(f"Got root hash: {node}")
            stack: List[str] = []
            add_to_db_cache: Dict[str, Any] = {}
            while node is not None:
                url = f"http://0.0.0.0:8080/get_tree_nodes?tree_id={tree_id}&node_hash={node}"
                async with session.get(url) as r:
                    json = await r.json()
                answer = json["answer"]
                for row in answer:
                    # Assert that we received correct left-to-right ordering.
                    assert node == row["hash"]
                    if row["is_terminal"]:
                        key = row["key"]
                        value = row["value"]
                        hash = Program.to((hexstr_to_bytes(key), hexstr_to_bytes(value))).get_tree_hash()
                        if hash == bytes32.from_hexstr(row["hash"]):
                            print(f"Validated terminal node {key} {value}.")
                            await self.data_store._insert_node(node, NodeType.TERMINAL, None, None, key, value)
                            print(f"Added terminal node {hash} to DB.")
                            right_hash = row["hash"]
                            while right_hash in add_to_db_cache:
                                node, left_hash = add_to_db_cache[right_hash]
                                del add_to_db_cache[right_hash]
                                await self.data_store._insert_node(
                                    node, NodeType.INTERNAL, left_hash, right_hash, None, None
                                )
                                print(f"Added internal node {node} to DB.")
                                right_hash = node
                        else:
                            raise RuntimeError(f"Can't validate terminal node {node}. Expected {hash}.")
                        if len(stack) > 0:
                            node = stack.pop()
                        else:
                            print("Finished validating tree.")
                            node = None
                    else:
                        left_hash = row["left"]
                        right_hash = row["right"]
                        left_hash_bytes = hexstr_to_bytes(left_hash)
                        right_hash_bytes = hexstr_to_bytes(right_hash)
                        hash = Program.to((left_hash_bytes, right_hash_bytes)).get_tree_hash(
                            left_hash_bytes, right_hash_bytes
                        )
                        if hash == bytes32.from_hexstr(row["hash"]):
                            print(f"Validated internal node {node}.")
                            add_to_db_cache[right_hash] = (node, left_hash)
                            assert len(add_to_db_cache) <= 100
                        else:
                            raise RuntimeError(f"Can't validate internal node {node}. Expected {hash}.")
                        if right_hash is not None:
                            stack.append(right_hash)
                        if left_hash is not None:
                            node = left_hash
                        elif len(stack) > 0:
                            node = stack.pop()
                        else:
                            print("Finished validating tree.")
                            node = None

            await self.data_store._insert_root(
                bytes32.from_hexstr(root_json["tree_id"]),
                bytes32.from_hexstr(root_json["node_hash"]),
                Status(root_json["status"]),
                root_json["generation"],
            )
            # Assert we downloaded everything.
            await self.data_store.check_tree_is_complete()


if __name__ == "__main__":
    data_layer_client = DataLayerClient()
    asyncio.run(data_layer_client.download_data_layer())
