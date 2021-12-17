import asyncio
import aiosqlite
import aiohttp
import time
from chia.data_layer.data_store import DataStore
from chia.util.db_wrapper import DBWrapper
from chia.types.blockchain_format.tree_hash import bytes32
from chia.types.blockchain_format.program import Program
from chia.util.byte_types import hexstr_to_bytes
from chia.data_layer.data_layer_types import Status, NodeType, Side
from typing import List, Any, Dict


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
            verbose = False
            tree_id = "0x0000000000000000000000000000000000000000000000000000000000000000"
            url = f"http://0.0.0.0:8080/get_tree_root?tree_id={tree_id}"
            async with session.get(url) as r:
                root_json = await r.json()
            node = root_hash = root_json["node_hash"]
            print(f"Got root hash: {node}")
            t1 = time.time()
            internal_nodes = 0
            terminal_nodes = 0
            stack: List[str] = []
            add_to_db_cache: Dict[str, Any] = {}
            while node is not None:
                url = f"http://0.0.0.0:8080/get_tree_nodes?tree_id={tree_id}&node_hash={node}&root_hash={root_hash}"
                async with session.get(url) as r:
                    json = await r.json()
                root_changed = json["root_changed"]
                if root_changed:
                    print("Data changed since the download started. Aborting.")
                    return
                answer = json["answer"]
                for row in answer:
                    if row["is_terminal"]:
                        key = row["key"]
                        value = row["value"]
                        hash = Program.to((hexstr_to_bytes(key), hexstr_to_bytes(value))).get_tree_hash()
                        if hash.hex() == node:
                            if verbose:
                                print(f"Received terminal node {key} {value}.")
                            await self.data_store._insert_node(node, NodeType.TERMINAL, None, None, key, value, tree_id)
                            if verbose:
                                print(f"Added terminal node {hash} to DB.")
                            terminal_nodes += 1
                            right_hash = hash.hex()
                            while right_hash in add_to_db_cache:
                                node, left_hash = add_to_db_cache[right_hash]
                                del add_to_db_cache[right_hash]
                                await self.data_store._insert_node(
                                    node, NodeType.INTERNAL, left_hash, right_hash, None, None, tree_id
                                )
                                internal_nodes += 1
                                if verbose:
                                    print(f"Added internal node {node} to DB.")
                                right_hash = node
                        else:
                            raise RuntimeError(
                                f"Did not received expected node. Expected: {node} Received: {hash.hex()}"
                            )
                        if len(stack) > 0:
                            node = stack.pop()
                        else:
                            node = None
                    else:
                        left_hash = row["left"]
                        right_hash = row["right"]
                        left_hash_bytes = hexstr_to_bytes(left_hash)
                        right_hash_bytes = hexstr_to_bytes(right_hash)
                        hash = Program.to((left_hash_bytes, right_hash_bytes)).get_tree_hash(
                            left_hash_bytes, right_hash_bytes
                        )
                        if hash.hex() == node:
                            if verbose:
                                print(f"Received internal node {node}.")
                            add_to_db_cache[right_hash] = (node, left_hash)
                            # At most max_height nodes will be pending to be added to DB.
                            assert len(add_to_db_cache) <= 100
                        else:
                            raise RuntimeError(
                                f"Did not received expected node. Expected: {node} Received: {hash.hex()}"
                            )
                        stack.append(right_hash)
                        node = left_hash

                print(f"Finished validating batch of {len(answer)}.")

            await self.data_store._insert_root(
                bytes32.from_hexstr(root_json["tree_id"]),
                bytes32.from_hexstr(root_json["node_hash"]),
                Status(root_json["status"]),
                root_json["generation"],
            )
            # Assert we downloaded everything.
            t2 = time.time()
            print("Finished validating tree.")
            print(f"Time taken: {t2 - t1}. Terminal nodes: {terminal_nodes} Internal nodes: {internal_nodes}.")

    async def download_data_layer_history(self) -> None:
        await self.init_db()
        async with aiohttp.ClientSession() as session:
            tree_id = "0x0000000000000000000000000000000000000000000000000000000000000000"
            url = f"http://0.0.0.0:8080/get_tree_root?tree_id={tree_id}"
            async with session.get(url) as r:
                root_json = await r.json()
            generation = root_json["generation"]
            added_generation = 1
            t1 = time.time()
            while added_generation < generation:
                url = f"http://0.0.0.0:8080/get_operations?tree_id={tree_id}&generation={added_generation}"
                async with session.get(url) as r:
                    json = await r.json()
                for row in json:
                    if row["is_insert"]:
                        await self.data_store.insert(
                            bytes.fromhex(row["key"]),
                            bytes.fromhex(row["value"]),
                            bytes32.from_hexstr(tree_id),
                            None
                            if row["reference_node_hash"] == "None"
                            else (bytes32.from_hexstr(row["reference_node_hash"])),
                            None
                            if row["reference_node_hash"] == "None"
                            else (Side.RIGHT if row["side"] == "right" else Side.LEFT),
                            status=Status(row["root_status"]),
                            skip_expensive_checks=True,
                        )
                    else:
                        await self.data_store.delete(
                            bytes.fromhex(row["key"]),
                            bytes32.from_hexstr(tree_id),
                            status=Status(row["root_status"]),
                            skip_expensive_checks=True,
                        )
                    print(f"Operation: {row}")
                    current_root = await self.data_store.get_tree_root(bytes32.from_hexstr(tree_id))
                    if current_root.node_hash is None:
                        assert row["hash"] == "None"
                    else:
                        assert current_root.node_hash.hex() == row["hash"]
                    added_generation += 1

        t2 = time.time()
        print("Finished downloading history.")
        print(f"Time taken: {t2 - t1}")


if __name__ == "__main__":
    data_layer_client = DataLayerClient()
    asyncio.run(data_layer_client.download_data_layer_history())
