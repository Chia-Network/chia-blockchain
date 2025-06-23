#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, Optional

import aiofiles
import click
from chia_rs.sized_bytes import bytes32

from chia.cmds.cmds_util import get_any_service_client
from chia.full_node.full_node_rpc_client import FullNodeRpcClient
from chia.util.default_root import resolve_root_path
from chia.util.path import path_from_root


def get_height_to_hash_filename(root_path: Path, config: dict[str, Any]) -> Path:
    """
    Utility function to get the path to the height-to-hash database file.
    """
    db_path_replaced: Path = root_path / config["full_node"]["database_path"]
    db_directory: Path = path_from_root(root_path, db_path_replaced).parent
    selected_network: str = config["full_node"]["selected_network"]
    suffix = "" if (selected_network is None or selected_network == "mainnet") else f"-{selected_network}"
    return db_directory / f"height-to-hash{suffix}"


async def get_block_cache_bytearray(root_path: Path, config: dict[str, Any], peak: int) -> bytearray:
    """
    Load the height-to-hash database file into a bytearray.
    """
    height_to_hash = bytearray()  # Init as bytearray to prep file loading
    height_to_hash_filename: Path = get_height_to_hash_filename(root_path, config)
    # Load the height-to-hash file
    async with aiofiles.open(height_to_hash_filename, "rb") as f:
        height_to_hash = bytearray(await f.read())
    # allocate memory for height to hash map
    # this may also truncate it, if the file on disk had an invalid size
    new_size = (peak + 1) * 32
    size = len(height_to_hash)
    if size > new_size:
        del height_to_hash[new_size:]
    else:
        height_to_hash += bytearray([0] * (new_size - size))
    return height_to_hash


def get_block_header_from_height(height: int, height_to_hash: bytearray) -> bytes32:
    """
    Get the block header hash from the height-to-hash database.
    """
    idx = height * 32
    assert idx + 32 <= len(height_to_hash)
    return bytes32(height_to_hash[idx : idx + 32])


@click.command(help="Test RPC endpoints using chain", no_args_is_help=True)
@click.option(
    "--root-path",
    default=resolve_root_path(override=None),
    help="Config file root",
    type=click.Path(),
    show_default=True,
)
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
)
@click.option(
    "-sc",
    "--spends_with_conditions",
    help="Test get_block_spends_with_conditions",
    is_flag=True,
    type=bool,
    default=False,
)
@click.option(
    "-sp",
    "--block_spends",
    help="Test get_block_spends",
    is_flag=True,
    type=bool,
    default=False,
)
@click.option(
    "-ar",
    "--additions_and_removals",
    help="Test get_additions_and_removals",
    is_flag=True,
    type=bool,
    default=False,
)
@click.option(
    "-s",
    "--start-height",
    help="Start height for the RPC calls",
    type=int,
    default=None,
)
@click.option(
    "-e",
    "--end-height",
    help="End height for the RPC calls",
    type=int,
    default=None,
)
@click.option(
    "-c",
    "--concurrent-requests",
    help="Number of concurrent requests to make to the RPC endpoints",
    type=int,
    default=50,
)
def cli(
    root_path: str,
    rpc_port: Optional[int],
    spends_with_conditions: bool,
    block_spends: bool,
    additions_and_removals: bool,
    concurrent_requests: int,
    start_height: Optional[int] = None,
    end_height: Optional[int] = None,
) -> None:
    root_path_path = Path(root_path)
    requests_per_batch = 0
    if spends_with_conditions:
        requests_per_batch += 1
    if block_spends:
        requests_per_batch += 1
    if additions_and_removals:
        requests_per_batch += 1
    if requests_per_batch == 0:
        print("No RPC calls selected. Exiting.")
        return
    concurrent_requests = max(1, concurrent_requests // requests_per_batch)
    if start_height is None:
        start_height = 0
    asyncio.run(
        cli_async(
            root_path=root_path_path,
            rpc_port=rpc_port,
            spends_with_conditions=spends_with_conditions,
            block_spends=block_spends,
            additions_and_removals=additions_and_removals,
            start_height=start_height,
            end_height=end_height,
            concurrent_requests=concurrent_requests,
        )
    )


async def cli_async(
    root_path: Path,
    rpc_port: Optional[int],
    spends_with_conditions: bool,
    block_spends: bool,
    additions_and_removals: bool,
    concurrent_requests: int,
    start_height: int,
    end_height: Optional[int] = None,
) -> None:
    blocks_per_status: int = 1000
    last_status_height: int = 0

    async with get_any_service_client(FullNodeRpcClient, root_path, rpc_port) as (
        node_client,
        config,
    ):
        blockchain_state: dict[str, Any] = await node_client.get_blockchain_state()
        if blockchain_state is None or blockchain_state["peak"] is None:
            # Peak height is required for thep cache.
            print("No blockchain found. Exiting.")
            return
        peak_height = blockchain_state["peak"].height
        assert peak_height is not None, "Blockchain peak height is None"
        if end_height is None:
            end_height = blockchain_state["peak"]["height"]

        print("Connected to Full Node")

        block_cache_bytearray: bytearray = await get_block_cache_bytearray(
            root_path=root_path,
            config=config,
            peak=peak_height,
        )

        print("Bytearray loaded with block header hashes from height-to-hash file.")

        # set initial segment heights
        start_segment: int = start_height
        end_segment: int = start_height + concurrent_requests

        while end_segment <= end_height:
            # Create an initial list to hold pending tasks
            pending_tasks: list[Coroutine[Any, Any, Any]] = []
            # measure time for performance measurement
            cycle_start: float = time.perf_counter()

            for i in range(start_segment, end_segment):
                block_header_hash: bytes32 = get_block_header_from_height(i, block_cache_bytearray)
                if spends_with_conditions:
                    pending_tasks.append(node_client.get_block_spends_with_conditions(block_header_hash))
                if block_spends:
                    pending_tasks.append(node_client.get_block_spends(block_header_hash))
                if additions_and_removals:
                    pending_tasks.append(node_client.get_additions_and_removals(block_header_hash))
            try:
                results = await asyncio.gather(*pending_tasks)
                for result in results:
                    if result is None:
                        raise ValueError("Received None from RPC call")
            except Exception as e:
                print(f"Error processing block range {start_segment} to {end_segment}: {e}")
                raise e
            # Print status every blocks_per_status blocks
            if end_segment - last_status_height >= blocks_per_status:
                print(f"Processed blocks {last_status_height} to {end_segment}")
                print(
                    f"Time taken for segment"
                    f" {last_status_height} to {end_segment}: {time.perf_counter() - cycle_start} seconds"
                )
                last_status_height = end_segment
                cycle_start = time.perf_counter()

            # reset variables for the next segment
            pending_tasks = []  # clear pending tasks after processing
            start_segment = end_segment
            end_segment += concurrent_requests
        print(f"Finished processing blocks from {start_height} to {end_height} (peak: {peak_height})")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
