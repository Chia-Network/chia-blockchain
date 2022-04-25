import aiohttp
import os
from pathlib import Path
from typing import List
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.data_layer.data_layer_types import NodeType, Status, SerializedNode
from chia.util.ints import uint16


def get_full_tree_filename(tree_id: bytes32, generation: int) -> str:
    return f"{tree_id}-{generation}-v1.0.dat"


def get_delta_filename(tree_id: bytes32, generation: int) -> str:
    return f"{tree_id}-delta-{generation}-v1.0.dat"


async def download_delta_files(
    tree_id: bytes32,
    existing_generation: int,
    target_generation: int,
    ip: str,
    port: uint16,
    client_foldername: Path,
) -> bool:
    while existing_generation + 1 <= target_generation:
        existing_generation += 1
        filename = get_delta_filename(tree_id, existing_generation)
        url = f"http://{ip}:{port}/{filename}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise RuntimeError("Didn't get 200 response status.")

                target_filename = os.path.join(client_foldername, filename)
                with open(target_filename, "wb") as writer:
                    text = await resp.read()
                    writer.write(text)
    return True


async def insert_from_delta_file(
    data_store: DataStore,
    tree_id: bytes32,
    root_hash: bytes32,
    filename: str,
) -> None:
    with open(filename, "rb") as reader:
        while True:
            chunk = reader.read(4)
            if chunk is None or chunk == b"":
                break

            size = int.from_bytes(chunk, byteorder="big")
            serialize_nodes_bytes = reader.read(size)
            serialized_node = SerializedNode.from_bytes(serialize_nodes_bytes)

            if serialized_node.is_terminal:
                await data_store.insert_node(NodeType.TERMINAL, serialized_node.value1, serialized_node.value2)
            else:
                await data_store.insert_node(NodeType.INTERNAL, serialized_node.value1, serialized_node.value2)

    await data_store.insert_batch_root(tree_id, root_hash, Status.COMMITTED)


async def parse_delta_files(
    data_store: DataStore,
    tree_id: bytes32,
    existing_generation: int,
    target_generation: int,
    root_hashes: List[bytes32],
    foldername: Path,
) -> None:
    for root_hash in root_hashes:
        existing_generation += 1
        filename = os.path.join(foldername, get_delta_filename(tree_id, existing_generation))
        await insert_from_delta_file(data_store, tree_id, root_hash, filename)
