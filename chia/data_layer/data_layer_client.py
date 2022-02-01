import json
import asyncio
import aiosqlite
import aiohttp
import time
from pathlib import Path
from typing import List, Any, Dict
from chia.data_layer.data_store import DataStore
from chia.util.db_wrapper import DBWrapper
from chia.types.blockchain_format.tree_hash import bytes32
from chia.types.blockchain_format.program import Program
from chia.util.byte_types import hexstr_to_bytes
from chia.data_layer.data_layer_types import Status, NodeType, Side
from dataclasses import dataclass
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.path import path_from_root, mkdir


@dataclass
class DataLayerClient:
    def __init__(self, config: Dict[Any, Any], db_path: Path):
        self.config = config
        self.db_path = db_path

    async def init_db(self) -> None:
        mkdir(self.db_path.parent)
        self.connection = await aiosqlite.connect(self.db_path)
        self.db_wrapper = DBWrapper(self.connection)
        self.data_store = await DataStore.create(db_wrapper=self.db_wrapper)
        tree_id = bytes32(b"\0" * 32)
        await self.data_store.create_tree(tree_id=tree_id)

    async def download_data_layer(self) -> None:
        await self.init_db()
        server_ip = self.config["server_ip"]
        server_port = self.config["server_port"]
        URL = f"http://{server_ip}:{server_port}/ws"

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(URL) as ws:
                tree_id = "0x0000000000000000000000000000000000000000000000000000000000000000"
                request = {
                    "type": "request_root",
                    "tree_id": tree_id,
                }
                await ws.send_str(json.dumps(request))
                msg = await ws.receive()
                root_json = json.loads(msg.data)
                node = root_hash = root_json["node_hash"]
                print(f"Got root hash: {node}")
                t1 = time.time()
                internal_nodes = 0
                terminal_nodes = 0
                stack: List[str] = []
                add_to_db_cache: Dict[str, Any] = {}

                while node is not None:
                    request = {
                        "type": "request_nodes",
                        "tree_id": tree_id,
                        "node_hash": node,
                        "root_hash": root_hash,
                    }
                    await ws.send_str(json.dumps(request))
                    msg = await ws.receive()
                    msg_json = json.loads(msg.data)
                    root_changed = msg_json["root_changed"]
                    if root_changed:
                        print("Data changed since the download started. Aborting.")
                        await ws.send_str(json.dumps({"type": "close"}))
                        return
                    answer = msg_json["answer"]
                    for row in answer:
                        if row["is_terminal"]:
                            key = row["key"]
                            value = row["value"]
                            hash = Program.to((hexstr_to_bytes(key), hexstr_to_bytes(value))).get_tree_hash()
                            if hash.hex() == node:
                                await self.data_store._insert_node(node, NodeType.TERMINAL, None, None, key, value)
                                terminal_nodes += 1
                                right_hash = hash.hex()
                                while right_hash in add_to_db_cache:
                                    node, left_hash = add_to_db_cache[right_hash]
                                    del add_to_db_cache[right_hash]
                                    await self.data_store._insert_node(
                                        node, NodeType.INTERNAL, left_hash, right_hash, None, None
                                    )
                                    internal_nodes += 1
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
                await ws.send_str(json.dumps({"type": "close"}))

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
        server_ip = self.config["server_ip"]
        server_port = self.config["server_port"]
        URL = f"http://{server_ip}:{server_port}/ws"

        tree_id = "0x0000000000000000000000000000000000000000000000000000000000000000"
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(URL) as ws:
                request = {
                    "type": "request_root",
                    "tree_id": tree_id,
                }
                await ws.send_str(json.dumps(request))
                msg = await ws.receive()
                root_json = json.loads(msg.data)
                generation = root_json["generation"]
                root = await self.data_store.get_tree_root(tree_id=bytes32(b"\0" * 32))
                existing_generation = root.generation + 1
                t1 = time.time()
                while existing_generation <= generation:
                    request = {
                        "type": "request_operations",
                        "tree_id": tree_id,
                        "generation": str(existing_generation),
                    }
                    await ws.send_str(json.dumps(request))
                    msg = await ws.receive()
                    msg_json = json.loads(msg.data)

                    for row in msg_json:
                        if row["is_insert"]:
                            await self.data_store.insert(
                                bytes.fromhex(row["key"]),
                                bytes.fromhex(row["value"]),
                                bytes32.from_hexstr(tree_id),
                                None
                                if row["reference_node_hash"] == "None"
                                else (bytes32.from_hexstr(row["reference_node_hash"])),
                                None if row["side"] == "None" else Side(row["side"]),
                                status=Status(row["root_status"]),
                            )
                        else:
                            await self.data_store.delete(
                                bytes.fromhex(row["key"]),
                                bytes32.from_hexstr(tree_id),
                                status=Status(row["root_status"]),
                            )
                        print(f"Operation: {row}")
                        current_root = await self.data_store.get_tree_root(bytes32.from_hexstr(tree_id))
                        if current_root.node_hash is None:
                            assert row["hash"] == "None"
                        else:
                            assert current_root.node_hash.hex() == row["hash"]
                        existing_generation += 1

                await ws.send_str(json.dumps({"type": "close"}))

        t2 = time.time()
        print("Finished downloading history.")
        print(f"Time taken: {t2 - t1}")


if __name__ == "__main__":
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml", "data_layer")
    db_path_replaced: str = config["client_database_path"].replace("CHALLENGE", config["selected_network"])
    db_path = path_from_root(DEFAULT_ROOT_PATH, db_path_replaced)

    data_layer_client = DataLayerClient(config, db_path)
    asyncio.run(data_layer_client.download_data_layer_history())
