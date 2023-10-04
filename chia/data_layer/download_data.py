from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import aiohttp
from typing_extensions import Literal

from chia.data_layer.data_layer_util import NodeType, PluginRemote, Root, SerializedNode, ServerInfo, Status
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32


def get_full_tree_filename(tree_id: bytes32, node_hash: bytes32, generation: int) -> str:
    return f"{tree_id}-{node_hash}-full-{generation}-v1.0.dat"


def get_delta_filename(tree_id: bytes32, node_hash: bytes32, generation: int) -> str:
    return f"{tree_id}-{node_hash}-delta-{generation}-v1.0.dat"


def is_filename_valid(filename: str) -> bool:
    split = filename.split("-")

    try:
        raw_tree_id, raw_node_hash, file_type, raw_generation, raw_version, *rest = split
        tree_id = bytes32(bytes.fromhex(raw_tree_id))
        node_hash = bytes32(bytes.fromhex(raw_node_hash))
        generation = int(raw_generation)
    except ValueError:
        return False

    if len(rest) > 0:
        return False

    # TODO: versions should probably be centrally defined
    if raw_version != "v1.0.dat":
        return False

    if file_type not in {"delta", "full"}:
        return False

    generate_file_func = get_delta_filename if file_type == "delta" else get_full_tree_filename
    reformatted = generate_file_func(tree_id=tree_id, node_hash=node_hash, generation=generation)

    return reformatted == filename


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
                    if size_to_read < 4:
                        raise Exception("Incomplete read of length.")
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
                    raise Exception("Incomplete read of blob.")
                serialize_nodes_bytes += cur_chunk
            serialized_node = SerializedNode.from_bytes(serialize_nodes_bytes)

            node_type = NodeType.TERMINAL if serialized_node.is_terminal else NodeType.INTERNAL
            await data_store.insert_node(node_type, serialized_node.value1, serialized_node.value2)

    await data_store.insert_root_with_ancestor_table(tree_id=tree_id, node_hash=root_hash, status=Status.COMMITTED)


@dataclass
class WriteFilesResult:
    result: bool
    full_tree: Optional[Path]
    diff_tree: Path


async def write_files_for_root(
    data_store: DataStore,
    tree_id: bytes32,
    root: Root,
    foldername: Path,
    full_tree_first_publish_generation: int,
    overwrite: bool = False,
) -> WriteFilesResult:
    if root.node_hash is not None:
        node_hash = root.node_hash
    else:
        node_hash = bytes32([0] * 32)  # todo change

    filename_full_tree = foldername.joinpath(get_full_tree_filename(tree_id, node_hash, root.generation))
    filename_diff_tree = foldername.joinpath(get_delta_filename(tree_id, node_hash, root.generation))

    written = False
    mode: Literal["wb", "xb"] = "wb" if overwrite else "xb"

    written_full_file = False
    if root.generation >= full_tree_first_publish_generation:
        try:
            with open(filename_full_tree, mode) as writer:
                await data_store.write_tree_to_file(root, node_hash, tree_id, False, writer)
            written = True
            written_full_file = True
        except FileExistsError:
            pass

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

    return WriteFilesResult(written, filename_full_tree if written_full_file else None, filename_diff_tree)


async def insert_from_delta_file(
    data_store: DataStore,
    tree_id: bytes32,
    existing_generation: int,
    root_hashes: List[bytes32],
    server_info: ServerInfo,
    client_foldername: Path,
    timeout: int,
    log: logging.Logger,
    proxy_url: str,
    downloader: Optional[PluginRemote],
) -> bool:
    for root_hash in root_hashes:
        timestamp = int(time.time())
        existing_generation += 1
        filename = get_delta_filename(tree_id, root_hash, existing_generation)
        request_json = {"url": server_info.url, "client_folder": str(client_foldername), "filename": filename}
        if downloader is None:
            # use http downloader
            if not await http_download(client_foldername, filename, proxy_url, server_info, timeout, log):
                break
        else:
            log.info(f"Using downloader {downloader} for store {tree_id.hex()}.")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    downloader.url + "/download",
                    json=request_json,
                    headers=downloader.headers,
                ) as response:
                    res_json = await response.json()
                    if not res_json["downloaded"]:
                        log.error(f"Failed to download delta file {filename} from {downloader}: {res_json}")
                        break

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
            await data_store.received_correct_file(tree_id, server_info)
        except Exception:
            target_filename = client_foldername.joinpath(filename)
            os.remove(target_filename)
            await data_store.received_incorrect_file(tree_id, server_info, timestamp)
            await data_store.rollback_to_generation(tree_id, existing_generation - 1)
            raise

    return True


def delete_full_file_if_exists(foldername: Path, tree_id: bytes32, root: Root) -> bool:
    if root.node_hash is not None:
        node_hash = root.node_hash
    else:
        node_hash = bytes32([0] * 32)  # todo change

    filename_full_tree = foldername.joinpath(get_full_tree_filename(tree_id, node_hash, root.generation))
    try:
        filename_full_tree.unlink()
    except FileNotFoundError:
        return False

    return True


async def http_download(
    client_folder: Path,
    filename: str,
    proxy_url: str,
    server_info: ServerInfo,
    timeout: int,
    log: logging.Logger,
) -> bool:
    async with aiohttp.ClientSession() as session:
        headers = {"accept-encoding": "gzip"}
        async with session.get(
            server_info.url + "/" + filename, headers=headers, timeout=timeout, proxy=proxy_url
        ) as resp:
            resp.raise_for_status()
            size = int(resp.headers.get("content-length", 0))
            log.debug(f"Downloading delta file {filename}. Size {size} bytes.")
            progress_byte = 0
            progress_percentage = "{:.0%}".format(0)
            target_filename = client_folder.joinpath(filename)
            with target_filename.open(mode="wb") as f:
                async for chunk, _ in resp.content.iter_chunks():
                    f.write(chunk)
                    progress_byte += len(chunk)
                    new_percentage = "{:.0%}".format(progress_byte / size)
                    if new_percentage != progress_percentage:
                        progress_percentage = new_percentage
                        log.info(f"Downloading delta file {filename}. {progress_percentage} of {size} bytes.")

    return True
