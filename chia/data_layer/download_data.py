from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import aiohttp
from typing_extensions import Literal

from chia.data_layer.data_layer_util import NodeType, PluginRemote, Root, SerializedNode, ServerInfo, Status
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32


def get_full_tree_filename(store_id: bytes32, node_hash: bytes32, generation: int, group_by_store: bool = False) -> str:
    if group_by_store:
        return f"{store_id}/{node_hash}-full-{generation}-v1.0.dat"
    return f"{store_id}-{node_hash}-full-{generation}-v1.0.dat"


def get_delta_filename(store_id: bytes32, node_hash: bytes32, generation: int, group_by_store: bool = False) -> str:
    if group_by_store:
        return f"{store_id}/{node_hash}-delta-{generation}-v1.0.dat"
    return f"{store_id}-{node_hash}-delta-{generation}-v1.0.dat"


def get_full_tree_filename_path(
    foldername: Path,
    store_id: bytes32,
    node_hash: bytes32,
    generation: int,
    group_by_store: bool = False,
) -> Path:
    if group_by_store:
        path = foldername.joinpath(f"{store_id}")
        return path.joinpath(f"{node_hash}-full-{generation}-v1.0.dat")
    return foldername.joinpath(f"{store_id}-{node_hash}-full-{generation}-v1.0.dat")


def get_delta_filename_path(
    foldername: Path,
    store_id: bytes32,
    node_hash: bytes32,
    generation: int,
    group_by_store: bool = False,
) -> Path:
    if group_by_store:
        path = foldername.joinpath(f"{store_id}")
        return path.joinpath(f"{node_hash}-delta-{generation}-v1.0.dat")
    return foldername.joinpath(f"{store_id}-{node_hash}-delta-{generation}-v1.0.dat")


def is_filename_valid(filename: str, group_by_store: bool = False) -> bool:
    if group_by_store:
        if filename.count("/") != 1:
            return False
        filename = filename.replace("/", "-")

    split = filename.split("-")

    try:
        raw_store_id, raw_node_hash, file_type, raw_generation, raw_version, *rest = split
        store_id = bytes32(bytes.fromhex(raw_store_id))
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
    reformatted = generate_file_func(
        store_id=store_id, node_hash=node_hash, generation=generation, group_by_store=False
    )

    return reformatted == filename


async def insert_into_data_store_from_file(
    data_store: DataStore,
    store_id: bytes32,
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

    await data_store.insert_root_with_ancestor_table(store_id=store_id, node_hash=root_hash, status=Status.COMMITTED)


@dataclass
class WriteFilesResult:
    result: bool
    full_tree: Optional[Path]
    diff_tree: Path


async def write_files_for_root(
    data_store: DataStore,
    store_id: bytes32,
    root: Root,
    foldername: Path,
    full_tree_first_publish_generation: int,
    overwrite: bool = False,
    group_by_store: bool = False,
) -> WriteFilesResult:
    if root.node_hash is not None:
        node_hash = root.node_hash
    else:
        node_hash = bytes32([0] * 32)  # todo change

    filename_full_tree = get_full_tree_filename_path(foldername, store_id, node_hash, root.generation, group_by_store)
    filename_diff_tree = get_delta_filename_path(foldername, store_id, node_hash, root.generation, group_by_store)
    filename_full_tree.parent.mkdir(parents=True, exist_ok=True)

    written = False
    mode: Literal["wb", "xb"] = "wb" if overwrite else "xb"

    written_full_file = False
    if root.generation >= full_tree_first_publish_generation:
        try:
            with open(filename_full_tree, mode) as writer:
                await data_store.write_tree_to_file(root, node_hash, store_id, False, writer)
            written = True
            written_full_file = True
        except FileExistsError:
            pass

    try:
        last_seen_generation = await data_store.get_last_tree_root_by_hash(
            store_id, root.node_hash, max_generation=root.generation
        )
        if last_seen_generation is None:
            with open(filename_diff_tree, mode) as writer:
                await data_store.write_tree_to_file(root, node_hash, store_id, True, writer)
        else:
            open(filename_diff_tree, mode).close()
        written = True
    except FileExistsError:
        pass

    return WriteFilesResult(written, filename_full_tree if written_full_file else None, filename_diff_tree)


async def download_file(
    data_store: DataStore,
    target_filename_path: Path,
    store_id: bytes32,
    root_hash: bytes32,
    generation: int,
    server_info: ServerInfo,
    proxy_url: str,
    downloader: Optional[PluginRemote],
    timeout: aiohttp.ClientTimeout,
    client_foldername: Path,
    timestamp: int,
    log: logging.Logger,
    grouped_by_store: bool,
    group_downloaded_files_by_store: bool,
) -> bool:
    if target_filename_path.exists():
        return True
    filename = get_delta_filename(store_id, root_hash, generation, grouped_by_store)

    if downloader is None:
        # use http downloader - this raises on any error
        try:
            await http_download(target_filename_path, filename, proxy_url, server_info, timeout, log)
        except (asyncio.TimeoutError, aiohttp.ClientError):
            new_server_info = await data_store.server_misses_file(store_id, server_info, timestamp)
            log.info(
                f"Failed to download {filename} from {new_server_info.url}."
                f"Miss {new_server_info.num_consecutive_failures}."
            )
            log.info(f"Next attempt from {new_server_info.url} in {new_server_info.ignore_till - timestamp}s.")
            return False
        return True

    log.info(f"Using downloader {downloader} for store {store_id.hex()}.")
    request_json = {
        "url": server_info.url,
        "client_folder": str(client_foldername),
        "filename": filename,
        "group_files_by_store": group_downloaded_files_by_store,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            downloader.url + "/download",
            json=request_json,
            headers=downloader.headers,
        ) as response:
            res_json = await response.json()
            assert isinstance(res_json["downloaded"], bool)
            return res_json["downloaded"]


async def insert_from_delta_file(
    data_store: DataStore,
    store_id: bytes32,
    existing_generation: int,
    root_hashes: List[bytes32],
    server_info: ServerInfo,
    client_foldername: Path,
    timeout: aiohttp.ClientTimeout,
    log: logging.Logger,
    proxy_url: str,
    downloader: Optional[PluginRemote],
    group_files_by_store: bool = False,
) -> bool:
    if group_files_by_store:
        client_foldername.joinpath(f"{store_id}").mkdir(parents=True, exist_ok=True)

    for root_hash in root_hashes:
        timestamp = int(time.time())
        existing_generation += 1
        target_filename_path = get_delta_filename_path(
            client_foldername, store_id, root_hash, existing_generation, group_files_by_store
        )
        filename_exists = target_filename_path.exists()
        for grouped_by_store in (False, True):
            success = await download_file(
                data_store=data_store,
                target_filename_path=target_filename_path,
                store_id=store_id,
                root_hash=root_hash,
                generation=existing_generation,
                server_info=server_info,
                proxy_url=proxy_url,
                downloader=downloader,
                timeout=timeout,
                client_foldername=client_foldername,
                timestamp=timestamp,
                log=log,
                grouped_by_store=grouped_by_store,
                group_downloaded_files_by_store=group_files_by_store,
            )
            if success:
                break
        else:
            return False

        log.info(f"Successfully downloaded delta file {target_filename_path.name}.")
        try:
            filename_full_tree = get_full_tree_filename_path(
                client_foldername,
                store_id,
                root_hash,
                existing_generation,
                group_files_by_store,
            )
            await insert_into_data_store_from_file(
                data_store,
                store_id,
                None if root_hash == bytes32([0] * 32) else root_hash,
                target_filename_path,
            )
            log.info(
                f"Successfully inserted hash {root_hash} from delta file. "
                f"Generation: {existing_generation}. Store id: {store_id}."
            )

            root = await data_store.get_tree_root(store_id=store_id)
            with open(filename_full_tree, "wb") as writer:
                await data_store.write_tree_to_file(root, root_hash, store_id, False, writer)
            log.info(f"Successfully written full tree filename {filename_full_tree}.")
            await data_store.received_correct_file(store_id, server_info)
        except Exception:
            try:
                target_filename_path.unlink()
            except FileNotFoundError:
                pass

            try:
                filename_full_tree.unlink()
            except FileNotFoundError:
                pass

            # await data_store.received_incorrect_file(store_id, server_info, timestamp)
            # incorrect file bans for 7 days which in practical usage
            # is too long given this file might be incorrect for various reasons
            # therefore, use the misses file logic instead
            if not filename_exists:
                # Don't penalize this server if we didn't download the file from it.
                await data_store.server_misses_file(store_id, server_info, timestamp)
            await data_store.rollback_to_generation(store_id, existing_generation - 1)
            return False

    return True


def delete_full_file_if_exists(foldername: Path, store_id: bytes32, root: Root) -> bool:
    if root.node_hash is not None:
        node_hash = root.node_hash
    else:
        node_hash = bytes32([0] * 32)  # todo change

    not_found = 0
    for group_by_store in (True, False):
        filename_full_tree = get_full_tree_filename_path(
            foldername, store_id, node_hash, root.generation, group_by_store
        )
        try:
            filename_full_tree.unlink()
        except FileNotFoundError:
            not_found += 1
        # File does not exist in both old and new path.
        if not_found == 2:
            return False

    return True


async def http_download(
    target_filename_path: Path,
    filename: str,
    proxy_url: str,
    server_info: ServerInfo,
    timeout: aiohttp.ClientTimeout,
    log: logging.Logger,
) -> None:
    """
    Download a file from a server using aiohttp.
    Raises exceptions on errors
    """
    async with aiohttp.ClientSession() as session:
        headers = {"accept-encoding": "gzip"}
        async with session.get(
            server_info.url + "/" + filename,
            headers=headers,
            timeout=timeout,
            proxy=proxy_url,
        ) as resp:
            resp.raise_for_status()
            size = int(resp.headers.get("content-length", 0))
            log.debug(f"Downloading delta file {filename}. Size {size} bytes.")
            progress_byte = 0
            progress_percentage = f"{0:.0%}"
            with target_filename_path.open(mode="wb") as f:
                async for chunk, _ in resp.content.iter_chunks():
                    f.write(chunk)
                    progress_byte += len(chunk)
                    new_percentage = f"{progress_byte / size:.0%}"
                    if new_percentage != progress_percentage:
                        progress_percentage = new_percentage
                        log.info(f"Downloading delta file {filename}. {progress_percentage} of {size} bytes.")
