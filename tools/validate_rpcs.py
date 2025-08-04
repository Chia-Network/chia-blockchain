#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional

import aiofiles
import click
from chia_rs.sized_bytes import bytes32

from chia.cmds.cmds_util import get_any_service_client
from chia.full_node.full_node_rpc_client import FullNodeRpcClient
from chia.util.default_root import resolve_root_path
from chia.util.path import path_from_root
from chia.util.task_referencer import create_referenced_task

DEFAULT_PIPELINE_DEPTH: int = 10


def get_height_to_hash_filename(root_path: Path, config: dict[str, Any]) -> Path:
    """
    Utility function to get the path to the height-to-hash database file.
    """
    db_path_replaced: Path = root_path / config["full_node"]["database_path"]
    db_directory: Path = path_from_root(root_path, db_path_replaced).parent
    selected_network: str = config["full_node"]["selected_network"]
    suffix = "" if (selected_network is None or selected_network == "mainnet") else f"-{selected_network}"
    return db_directory / f"height-to-hash{suffix}"


async def get_height_to_hash_bytes(root_path: Path, config: dict[str, Any]) -> bytes:
    """
    Load the height-to-hash database file into a bytearray.
    """
    height_to_hash_filename: Path = get_height_to_hash_filename(root_path, config)
    async with aiofiles.open(height_to_hash_filename, "rb") as f:
        return await f.read()


def get_block_hash_from_height(height: int, height_to_hash: bytes) -> bytes32:
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
    "-r",
    "--pipeline-depth",
    help="Set the number of concurrent RPC calls to make.",
    type=int,
    default=DEFAULT_PIPELINE_DEPTH,
)
def cli(
    root_path: str,
    rpc_port: Optional[int],
    spends_with_conditions: bool,
    block_spends: bool,
    additions_and_removals: bool,
    pipeline_depth: int,
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
            pipeline_depth=pipeline_depth,
        )
    )


async def node_spends_with_conditions(
    node_client: FullNodeRpcClient,
    block_hash: bytes32,
    height: int,
) -> None:
    try:
        await node_client.get_block_spends_with_conditions(block_hash)
    except Exception as e:
        print(f"ERROR: [{height}] get_block_spends_with_conditions returned invalid result")
        raise e


async def node_block_spends(
    node_client: FullNodeRpcClient,
    block_hash: bytes32,
    height: int,
) -> None:
    try:
        await node_client.get_block_spends(block_hash)
    except Exception as e:
        print(f"ERROR: [{height}] get_block_spends returned invalid result")
        raise e


async def node_additions_removals(
    node_client: FullNodeRpcClient,
    block_hash: bytes32,
    height: int,
) -> None:
    try:
        await node_client.get_additions_and_removals(block_hash)
    except Exception as e:
        print(f"ERROR: [{height}] get_additions_and_removals returned invalid result")
        raise e


async def cli_async(
    root_path: Path,
    rpc_port: Optional[int],
    spends_with_conditions: bool,
    block_spends: bool,
    additions_and_removals: bool,
    pipeline_depth: int,
    start_height: int,
    end_height: Optional[int] = None,
) -> None:
    async with get_any_service_client(FullNodeRpcClient, root_path, rpc_port) as (
        node_client,
        config,
    ):
        blockchain_state: dict[str, Any] = await node_client.get_blockchain_state()
        if blockchain_state is None or blockchain_state["peak"] is None:
            # Peak height is required for the cache.
            print("No blockchain found. Exiting.")
            return
        peak_height = blockchain_state["peak"].height
        assert peak_height is not None, "Blockchain peak height is None"
        if end_height is None:
            end_height = peak_height

        print("Connected to Full Node")

        height_to_hash_bytes: bytes = await get_height_to_hash_bytes(root_path=root_path, config=config)

        print("block header hashes loaded from height-to-hash file.")

        # Set initial values for the loop

        pipeline: set[asyncio.Task[None]] = set()
        completed_requests: int = 0
        # measure time for performance measurement per segment
        cycle_start: float = time.monotonic()
        # also measure time for the whole process
        start_time: float = cycle_start

        def add_tasks_for_height(height: int) -> None:
            block_header_hash = get_block_hash_from_height(height, height_to_hash_bytes)
            # Create tasks for each RPC call based on the flags
            if spends_with_conditions:
                pipeline.add(
                    create_referenced_task(node_spends_with_conditions(node_client, block_header_hash, height))
                )
            if block_spends:
                pipeline.add(create_referenced_task(node_block_spends(node_client, block_header_hash, height)))
            if additions_and_removals:
                pipeline.add(create_referenced_task(node_additions_removals(node_client, block_header_hash, height)))

        for i in range(start_height, end_height + 1):
            add_tasks_for_height(height=i)
            # Make Status Updates.
            if len(pipeline) >= pipeline_depth:
                done, pipeline = await asyncio.wait(pipeline, return_when=asyncio.FIRST_COMPLETED)
                completed_requests += len(done)
                now = time.monotonic()
                if cycle_start + 5 < now:
                    time_taken = now - cycle_start
                    print(
                        f"Processed {completed_requests} RPCs in {time_taken:.2f}s, "
                        f"{time_taken / completed_requests:.4f}s per RPC "
                        f"({i - start_height} Blocks completed out of {end_height - start_height})"
                    )
                    completed_requests = 0
                    cycle_start = now

        # Wait for any remaining tasks to complete
        print(f"Waiting for {len(pipeline)} remaining tasks to complete...")
        if pipeline:
            await asyncio.gather(*pipeline)

        print(f"Finished processing blocks from {start_height} to {end_height} (peak: {peak_height})")
        print(
            f"Time per block for the whole process: "
            f"{(time.monotonic() - start_time) / (end_height - start_height):.4f} seconds"
        )


if __name__ == "__main__":
    cli()
