import aiohttp
import json
from typing import List, Tuple, Dict, Any
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.data_layer.data_layer_types import NodeType, Status, Subscription, Side, DownloadMode
from chia.types.blockchain_format.program import Program
from chia.util.byte_types import hexstr_to_bytes


async def download_data_latest(
    data_store: DataStore, tree_id: bytes32, target_hash: bytes32, URL: str, *, lock: bool = True
) -> bool:
    insert_batch: List[Tuple[NodeType, bytes32, bytes32]] = []

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(URL) as ws:
            request = {
                "type": "request_root",
                "tree_id": tree_id.hex(),
                "node_hash": target_hash.hex(),
            }
            await ws.send_str(json.dumps(request))
            msg = await ws.receive()
            root_json = json.loads(msg.data)
            node = root_json["node_hash"]
            stack: List[str] = []
            add_to_db_cache: Dict[str, Any] = {}

            # TODO: Add back pagination. This needs historical ancestors.
            request = {
                "type": "request_nodes",
                "tree_id": tree_id.hex(),
                "node_hash": node,
            }
            await ws.send_str(json.dumps(request))
            msg = await ws.receive()
            msg_json = json.loads(msg.data)
            answer = msg_json["answer"]
            for row in answer:
                if row["is_terminal"]:
                    key = row["key"]
                    value = row["value"]
                    hash = Program.to((hexstr_to_bytes(key), hexstr_to_bytes(value))).get_tree_hash()
                    if hash.hex() == node:
                        insert_batch.append((NodeType.TERMINAL, key, value))
                        right_hash = hash.hex()
                        while right_hash in add_to_db_cache:
                            node, left_hash = add_to_db_cache[right_hash]
                            del add_to_db_cache[right_hash]
                            insert_batch.append((NodeType.INTERNAL, left_hash, right_hash))
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
                    left_hash_bytes = bytes32.from_hexstr(left_hash)
                    right_hash_bytes = bytes32.from_hexstr(right_hash)
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

            if node is not None:
                raise RuntimeError("Did not download full data.")
            await ws.send_str(json.dumps({"type": "close"}))

    await data_store.insert_batch_for_generation(
        insert_batch, tree_id, bytes32.from_hexstr(root_json["node_hash"]), int(root_json["generation"]), lock=lock
    )
    return True


async def download_data_history(
    data_store: DataStore, tree_id: bytes32, target_hash: bytes32, URL: str, *, lock: bool = True
) -> bool:
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(URL) as ws:
            request = {
                "type": "request_root",
                "tree_id": tree_id.hex(),
                "node_hash": target_hash.hex(),
            }
            await ws.send_str(json.dumps(request))
            msg = await ws.receive()
            root_json = json.loads(msg.data)
            generation = root_json["generation"]
            root = await data_store.get_tree_root(tree_id=tree_id, lock=lock)
            existing_generation = root.generation + 1
            while existing_generation <= generation:
                request = {
                    "type": "request_operations",
                    "tree_id": tree_id.hex(),
                    "generation": str(existing_generation),
                    "max_generation": str(generation),
                }
                await ws.send_str(json.dumps(request))
                msg = await ws.receive()
                msg_json = json.loads(msg.data)

                for row in msg_json:
                    if row["is_insert"]:
                        await data_store.insert(
                            bytes.fromhex(row["key"]),
                            bytes.fromhex(row["value"]),
                            tree_id,
                            None
                            if row["reference_node_hash"] == "None"
                            else (bytes32.from_hexstr(row["reference_node_hash"])),
                            None if row["side"] == "None" else Side(row["side"]),
                            status=Status(row["root_status"]),
                            lock=lock,
                        )
                    else:
                        await data_store.delete(
                            bytes.fromhex(row["key"]),
                            tree_id,
                            status=Status(row["root_status"]),
                            lock=lock,
                        )
                    current_root = await data_store.get_tree_root(tree_id, lock=lock)
                    if current_root.node_hash is None:
                        if row["hash"] != "None":
                            return False
                    else:
                        if current_root.node_hash.hex() != row["hash"]:
                            return False
                    existing_generation += 1

            await ws.send_str(json.dumps({"type": "close"}))

    return True


async def download_data(
    data_store: DataStore,
    subscription: Subscription,
    target_hash: bytes32,
    *,
    lock: bool = True
) -> bool:
    tree_id = subscription.tree_id
    ip = subscription.ip
    port = int(subscription.port)
    exists = await data_store.tree_id_exists(tree_id)
    if not exists:
        await data_store.create_tree(tree_id=tree_id, status=Status.COMMITTED)
    URL = f"http://{ip}:{port}/ws"

    if subscription.mode is DownloadMode.LATEST:
        return await download_data_latest(data_store, tree_id, target_hash, URL, lock=lock)
    elif subscription.mode is DownloadMode.HISTORY:
        return await download_data_history(data_store, tree_id, target_hash, URL, lock=lock)
    return False
