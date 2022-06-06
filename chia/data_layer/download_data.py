import aiohttp
import asyncio
import os
import logging
from pathlib import Path
from typing import List, Optional
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.data_layer.data_layer_types import NodeType, Status, SerializedNode, Root
from chia.util.ints import uint16


def get_full_tree_filename(tree_id: bytes32, node_hash: bytes32, generation: int) -> str:
    return f"{tree_id}-{node_hash}-{generation}-v1.0.dat"


def get_delta_filename(tree_id: bytes32, node_hash: bytes32, generation: int) -> str:
    return f"{tree_id}-{node_hash}-delta-{generation}-v1.0.dat"


async def insert_into_data_store_from_file(
    data_store: DataStore,
    tree_id: bytes32,
    root_hash: Optional[bytes32],
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

            node_type = NodeType.TERMINAL if serialized_node.is_terminal else NodeType.INTERNAL
            await data_store.insert_node(node_type, serialized_node.value1, serialized_node.value2)

    await data_store.insert_root(tree_id=tree_id, node_hash=root_hash, status=Status.COMMITTED)
    await data_store.build_ancestor_table_from_root(tree_id)


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
    filename_full_tree = os.path.join(foldername, get_full_tree_filename(tree_id, node_hash, root.generation))
    filename_diff_tree = os.path.join(foldername, get_delta_filename(tree_id, node_hash, root.generation))
    written = False
    if override and os.path.exists(filename_full_tree):
        os.remove(filename_full_tree)
    if not os.path.exists(filename_full_tree):
        await data_store.write_tree_to_file(root, node_hash, tree_id, False, filename_full_tree)
        written = True
    if override and os.path.exists(filename_diff_tree):
        os.remove(filename_diff_tree)
    if not os.path.exists(filename_diff_tree):
        last_seen_generation = await data_store.get_last_tree_root_by_hash(
            tree_id, root.node_hash, max_generation=root.generation
        )
        if last_seen_generation is None:
            await data_store.write_tree_to_file(root, node_hash, tree_id, True, filename_diff_tree)
        else:
            open(filename_diff_tree, "ab").close()
        written = True
    return written


async def insert_from_delta_file(
    data_store: DataStore,
    tree_id: bytes32,
    existing_generation: int,
    root_hashes: List[bytes32],
    ip: str,
    port: uint16,
    client_foldername: Path,
    log: logging.Logger,
) -> bool:
    for root_hash in root_hashes:
        existing_generation += 1
        filename = get_delta_filename(tree_id, root_hash, existing_generation)
        url = f"http://{ip}:{port}/{filename}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    resp.raise_for_status()

                    target_filename = os.path.join(client_foldername, filename)
                    with open(target_filename, "wb") as writer:
                        text = await resp.read()
                        writer.write(text)
        except asyncio.CancelledError:
            raise
        except Exception:
            if await data_store.get_last_tree_root_by_hash(tree_id, root_hash) is not None:
                # If we don't have the delta file, but we have the tree in the past, create an empty delta file.
                # It's possible the wallet record to be created by a proof of inclusion, not a batch update,
                # hence the delta file might be missing.
                log.info(f"Already seen {root_hash} for {tree_id}. Writing an empty delta file.")
                open(filename, "ab").close()
            else:
                raise

        log.info(f"Successfully downloaded delta file {filename}.")
        try:
            await insert_into_data_store_from_file(
                data_store,
                tree_id,
                None if root_hash == bytes32([0] * 32) else root_hash,
                os.path.join(client_foldername, filename),
            )
            log.info(
                f"Successfully inserted hash {root_hash} from delta file. "
                f"Generation: {existing_generation}. Tree id: {tree_id}."
            )

            filename_full_tree = get_full_tree_filename(tree_id, root_hash, existing_generation)
            root = await data_store.get_tree_root(tree_id=tree_id)
            await data_store.write_tree_to_file(root, root_hash, tree_id, False, filename_full_tree)
            log.info(f"Successfully written full tree filename {filename_full_tree}.")
        except asyncio.CancelledError:
            raise
        except Exception:
            os.remove(filename)
            await data_store.rollback_to_generation(tree_id, existing_generation - 1)
            raise

    return True
