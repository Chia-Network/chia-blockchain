#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import aiosqlite
import click
import zstd

from chia._tests.util.full_sync import FakePeer, FakeServer, run_sync_test
from chia.cmds.init_funcs import chia_init
from chia.consensus.constants import replace_str_to_bytes
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.full_node.full_node import FullNode
from chia.server.ws_connection import WSChiaConnection
from chia.types.full_block import FullBlock
from chia.util.config import load_config


@click.group()
def main() -> None:
    pass


@main.command("run", help="run simulated full sync from an existing blockchain db")
@click.argument("file", type=click.Path(), required=True)
@click.option("--db-version", type=int, required=False, default=2, help="the DB version to use in simulated node")
@click.option("--profile", is_flag=True, required=False, default=False, help="dump CPU profiles for slow batches")
@click.option("--db-sync", type=str, required=False, default="off", help="sqlite sync mode. One of: off, normal, full")
@click.option("--node-profiler", is_flag=True, required=False, default=False, help="enable the built-in node-profiler")
@click.option(
    "--test-constants",
    is_flag=True,
    required=False,
    default=False,
    help="expect the blockchain database to be blocks using the test constants",
)
@click.option(
    "--single-thread",
    is_flag=True,
    required=False,
    default=False,
    help="run node in a single process, to include validation in profiles",
)
@click.option(
    "--keep-up",
    is_flag=True,
    required=False,
    default=False,
    help="pass blocks to the full node as if we're staying synced, rather than syncing",
)
@click.option(
    "--start-at-checkpoint",
    type=click.Path(),
    required=False,
    default=None,
    help="start test from this specified checkpoint state",
)
def run(
    file: Path,
    db_version: int,
    profile: bool,
    single_thread: bool,
    test_constants: bool,
    keep_up: bool,
    db_sync: str,
    node_profiler: bool,
    start_at_checkpoint: Optional[str],
) -> None:
    """
    The FILE parameter should point to an existing blockchain database file (in v2 format)
    """
    print(f"PID: {os.getpid()}")
    asyncio.run(
        run_sync_test(
            Path(file),
            db_version,
            profile,
            single_thread,
            test_constants,
            keep_up,
            db_sync,
            node_profiler,
            start_at_checkpoint,
        )
    )


@main.command("analyze", help="generate call stacks for all profiles dumped to current directory")
def analyze() -> None:
    from glob import glob
    from shlex import quote
    from subprocess import check_call

    for input_file in glob("slow-batch-*.profile"):
        output = input_file.replace(".profile", ".png")
        print(f"{input_file}")
        check_call(f"gprof2dot -f pstats {quote(input_file)} | dot -T png >{quote(output)}", shell=True)


@main.command("create-checkpoint", help="sync the full node up to specified height and save its state")
@click.argument("file", type=click.Path(), required=True)
@click.argument("out-file", type=click.Path(), required=True)
@click.option("--height", type=int, required=True, help="Sync node up to this height")
def create_checkpoint(file: Path, out_file: Path, height: int) -> None:
    """
    The FILE parameter should point to an existing blockchain database file (in v2 format)
    """
    asyncio.run(run_sync_checkpoint(Path(file), Path(out_file), height))


async def run_sync_checkpoint(
    file: Path,
    root_path: Path,
    max_height: int,
) -> None:
    root_path.mkdir(parents=True, exist_ok=True)

    chia_init(root_path, should_check_keys=False, v1_db=False)
    config = load_config(root_path, "config.yaml")

    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    constants = replace_str_to_bytes(DEFAULT_CONSTANTS, **overrides)
    config["full_node"]["db_sync"] = "off"
    full_node = await FullNode.create(
        config["full_node"],
        root_path=root_path,
        consensus_constants=constants,
    )

    full_node.set_server(FakeServer())  # type: ignore[arg-type]
    async with full_node.manage():
        peer: WSChiaConnection = FakePeer()  # type: ignore[assignment]

        print()
        height = 0
        async with aiosqlite.connect(file) as in_db:
            await in_db.execute("pragma query_only")
            rows = await in_db.execute(
                "SELECT block FROM full_blocks WHERE in_main_chain=1 AND height < ? ORDER BY height", (max_height,)
            )

            block_batch = []
            peer_info = peer.get_peer_logging()
            async for r in rows:
                block = FullBlock.from_bytes_unchecked(zstd.decompress(r[0]))
                block_batch.append(block)

                if len(block_batch) < 32:
                    continue

                block_record = await full_node.blockchain.get_block_record_from_db(block_batch[0].prev_header_hash)
                ssi, diff = get_next_sub_slot_iters_and_difficulty(
                    full_node.constants, True, block_record, full_node.blockchain
                )
                success, _, _, _, _, _ = await full_node.add_block_batch(
                    block_batch, peer_info, None, current_ssi=ssi, current_difficulty=diff
                )
                end_height = block_batch[-1].height
                full_node.blockchain.clean_block_record(end_height - full_node.constants.BLOCKS_CACHE_SIZE)

                if not success:
                    raise RuntimeError("failed to ingest block batch")

                height += len(block_batch)
                print(f"\rheight {height}    ", end="")
                block_batch = []

            if len(block_batch) > 0:
                block_record = await full_node.blockchain.get_block_record_from_db(block_batch[0].prev_header_hash)
                ssi, diff = get_next_sub_slot_iters_and_difficulty(
                    full_node.constants, True, block_record, full_node.blockchain
                )
                success, _, _, _, _, _ = await full_node.add_block_batch(
                    block_batch, peer_info, None, current_ssi=ssi, current_difficulty=diff
                )
                if not success:
                    raise RuntimeError("failed to ingest block batch")


main.add_command(run)
main.add_command(analyze)

if __name__ == "__main__":
    # pylint: disable = no-value-for-parameter
    main()
