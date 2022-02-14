#!/usr/bin/env python3

import asyncio
import cProfile
import logging
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import aiosqlite
import click
import zstd

from chia.cmds.init_funcs import chia_init
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.full_node import FullNode
from chia.types.full_block import FullBlock
from chia.util.config import load_config


class ExitOnError(logging.Handler):
    def __init__(self):
        super().__init__()
        self.exit_with_failure = False

    def emit(self, record):
        if record.levelno != logging.ERROR:
            return
        self.exit_with_failure = True


@contextmanager
def enable_profiler(profile: bool, counter: int) -> Iterator[None]:
    if not profile:
        yield
        return

    with cProfile.Profile() as pr:
        receive_start_time = time.monotonic()
        yield

    if time.monotonic() - receive_start_time > 10:
        pr.create_stats()
        pr.dump_stats(f"slow-batch-{counter:05d}.profile")


async def run_sync_test(file: Path, db_version, profile: bool) -> None:

    logger = logging.getLogger()
    logger.setLevel(logging.WARNING)
    handler = logging.FileHandler("test-full-sync.log")
    handler.setFormatter(
        logging.Formatter(
            "%(levelname)-8s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    logger.addHandler(handler)
    check_log = ExitOnError()
    logger.addHandler(check_log)

    with tempfile.TemporaryDirectory() as root_dir:

        root_path = Path(root_dir)
        chia_init(root_path, should_check_keys=False)
        config = load_config(root_path, "config.yaml")

        overrides = config["network_overrides"]["constants"][config["selected_network"]]
        constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
        full_node = FullNode(
            config["full_node"],
            root_path=root_path,
            consensus_constants=constants,
        )

        try:
            await full_node._start()

            print()
            counter = 0
            async with aiosqlite.connect(file) as in_db:

                rows = await in_db.execute("SELECT header_hash, height, block FROM full_blocks ORDER BY height")

                block_batch = []

                start_time = time.monotonic()
                async for r in rows:
                    block = FullBlock.from_bytes(zstd.decompress(r[2]))

                    block_batch.append(block)
                    if len(block_batch) < 32:
                        continue

                    with enable_profiler(profile, counter):
                        success, advanced_peak, fork_height, coin_changes = await full_node.receive_block_batch(
                            block_batch, None, None  # type: ignore[arg-type]
                        )

                    assert success
                    assert advanced_peak
                    counter += len(block_batch)
                    print(f"\rheight {counter} {counter/(time.monotonic() - start_time):0.2f} blocks/s   ", end="")
                    block_batch = []
                    if check_log.exit_with_failure:
                        raise RuntimeError("error printed to log. exiting")
        finally:
            print("closing full node")
            full_node._close()
            await full_node._await_closed()


@click.group()
def main() -> None:
    pass


@main.command("run", short_help="run simulated full sync from an existing blockchain db")
@click.argument("file", type=click.Path(), required=True)
@click.option("--db-version", type=int, required=False, default=2, help="the version of the specified db file")
@click.option("--profile", is_flag=True, required=False, default=False, help="dump CPU profiles for slow batches")
def run(file: Path, db_version: int, profile: bool) -> None:
    asyncio.run(run_sync_test(Path(file), db_version, profile))


@main.command("analyze", short_help="generate call stacks for all profiles dumped to current directory")
def analyze() -> None:
    from glob import glob
    from shlex import quote
    from subprocess import check_call

    for input_file in glob("slow-batch-*.profile"):
        output = input_file.replace(".profile", ".png")
        print(f"{input_file}")
        check_call(f"gprof2dot -f pstats {quote(input_file)} | dot -T png >{quote(output)}", shell=True)


main.add_command(run)
main.add_command(analyze)

if __name__ == "__main__":
    # pylint: disable = no-value-for-parameter
    main()
