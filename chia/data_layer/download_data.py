import aiohttp
import asyncio
import os
import logging
from pathlib import Path
from typing import List, Optional
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.data_layer.data_layer_types import NodeType, Status, SerializedNode, Root


def get_full_tree_filename(tree_id: bytes32, node_hash: bytes32, generation: int) -> str:
    return f"{tree_id}-{node_hash}-full-{generation}-v1.0.dat"


def get_delta_filename(tree_id: bytes32, node_hash: bytes32, generation: int) -> str:
    return f"{tree_id}-{node_hash}-delta-{generation}-v1.0.dat"


def is_filename_valid(filename: str) -> bool:
    try:
        if len(filename) > 200:
            return False
        if not filename.endswith("-v1.0.dat"):
            return False
        filename = filename[:-9]
        tree_id_bytes = bytes.fromhex(filename[:64])
        if len(tree_id_bytes) != 32:
            return False
        filename = filename[64:]
        if filename[0] != "-":
            return False
        filename = filename[1:]
        node_hash_bytes = bytes.fromhex(filename[:64])
        if len(node_hash_bytes) != 32:
            return False
        filename = filename[64:]
        if filename[0] != "-":
            return False
        filename = filename[1:]
        if filename.startswith("delta"):
            filename = filename[5:]
        elif filename.startswith("full"):
            filename = filename[4:]
        else:
            return False
        if filename[0] != "-":
            return False
        filename = filename[1:]
        generation = int(filename)
        if generation < 0 or generation > 1000000000:
            return False
        return True
    except Exception:
        return False


async def insert_into_data_store_from_file(
    data_store: DataStore,
    tree_id: bytes32,
    root_hash: Optional[bytes32],
    filename: Path,
) -> None:
    with open(filename, "rb") as reader:
        while True:
            chunk = b""
            while len(chunk) < 4:
                size_to_read = 4 - len(chunk)
                cur_chunk = reader.read(size_to_read)
                if cur_chunk is None or cur_chunk == b"":
                    break
                chunk += cur_chunk
            if chunk == b"":
                break

            size = int.from_bytes(chunk, byteorder="big")
            serialize_nodes_bytes = b""
            while len(serialize_nodes_bytes) < size:
                size_to_read = size - len(serialize_nodes_bytes)
                cur_chunk = reader.read(size_to_read)
                if cur_chunk is None or cur_chunk == b"":
                    break
                serialize_nodes_bytes += cur_chunk
            serialized_node = SerializedNode.from_bytes(serialize_nodes_bytes)

            node_type = NodeType.TERMINAL if serialized_node.is_terminal else NodeType.INTERNAL
            await data_store.insert_node(node_type, serialized_node.value1, serialized_node.value2)

    await data_store.insert_root_with_ancestor_table(tree_id=tree_id, node_hash=root_hash, status=Status.COMMITTED)


async def write_files_for_root(
    data_store: DataStore,
    tree_id: bytes32,
    root: Root,
    foldername: Path,
    override: bool = False,
) -> bool:
    if root.node_hash is not None:
        node_hash = root.node_hash
    else:
        node_hash = bytes32([0] * 32)  # todo change

    filename_full_tree = foldername.joinpath(get_full_tree_filename(tree_id, node_hash, root.generation))
    filename_diff_tree = foldername.joinpath(get_delta_filename(tree_id, node_hash, root.generation))

    written = False
    mode = "wb" if override else "xb"

    try:
        with open(filename_full_tree, mode) as writer:
            await data_store.write_tree_to_file(root, node_hash, tree_id, False, writer)
        written = True
    except FileExistsError:
        pass
    except Exception:
        raise

    try:
        last_seen_generation = await data_store.get_last_tree_root_by_hash(
            tree_id, root.node_hash, max_generation=root.generation
        )
        if last_seen_generation is None:
            with open(filename_diff_tree, mode) as writer:
                await data_store.write_tree_to_file(root, node_hash, tree_id, True, writer)
        else:
            open(filename_diff_tree, mode).close()
        written = True
    except FileExistsError:
        pass
    except Exception:
        raise

    return written


async def insert_from_delta_file(
    data_store: DataStore,
    tree_id: bytes32,
    existing_generation: int,
    root_hashes: List[bytes32],
    url: str,
    client_foldername: Path,
    log: logging.Logger,
) -> bool:
    for root_hash in root_hashes:
        existing_generation += 1
        filename = get_delta_filename(tree_id, root_hash, existing_generation)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url + "/" + filename) as resp:
                    resp.raise_for_status()

                    target_filename = client_foldername.joinpath(filename)
                    text = await resp.read()
                    target_filename.write_bytes(text)
        except Exception:
            raise

        log.info(f"Successfully downloaded delta file {filename}.")
        try:
            await insert_into_data_store_from_file(
                data_store,
                tree_id,
                None if root_hash == bytes32([0] * 32) else root_hash,
                client_foldername.joinpath(filename),
            )
            log.info(
                f"Successfully inserted hash {root_hash} from delta file. "
                f"Generation: {existing_generation}. Tree id: {tree_id}."
            )

            filename_full_tree = client_foldername.joinpath(
                get_full_tree_filename(tree_id, root_hash, existing_generation)
            )
            root = await data_store.get_tree_root(tree_id=tree_id)
            with open(filename_full_tree, "wb") as writer:
                await data_store.write_tree_to_file(root, root_hash, tree_id, False, writer)
            log.info(f"Successfully written full tree filename {filename_full_tree}.")
        except asyncio.CancelledError:
            raise
        except Exception:
            target_filename = client_foldername.joinpath(filename)
            os.remove(target_filename)
            await data_store.rollback_to_generation(tree_id, existing_generation - 1)
            raise

    return True
