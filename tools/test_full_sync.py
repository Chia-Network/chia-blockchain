#!/usr/bin/env python3

import asyncio
import aiosqlite
import zstd
import click
import logging
from pathlib import Path
from time import time
import tempfile

from chia.types.full_block import FullBlock
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.util.config import load_config
from chia.full_node.full_node import FullNode

from chia.cmds.init_funcs import chia_init


async def run_sync_test(file: Path, db_version=2) -> None:

    logger = logging.getLogger()
    logger.setLevel(logging.WARNING)
    handler = logging.FileHandler("test-full-sync.log")
    handler.setFormatter(
        logging.Formatter(
            "\n%(levelname)-8s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    logger.addHandler(handler)

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

                start_time = time()
                async for r in rows:
                    block = FullBlock.from_bytes(zstd.decompress(r[2]))

                    block_batch.append(block)
                    if len(block_batch) < 32:
                        continue

                    success, advanced_peak, fork_height, coin_changes = await full_node.receive_block_batch(
                        block_batch, None, None  # type: ignore[arg-type]
                    )
                    assert success
                    assert advanced_peak
                    counter += len(block_batch)
                    print(f"\rheight {counter} {counter/(time() - start_time):0.2f} blocks/s   ", end="")
                    block_batch = []
        finally:
            print("closing full node")
            full_node._close()
            await full_node._await_closed()


@click.command()
@click.argument("file", type=click.Path(), required=True)
@click.argument("db-version", type=int, required=False, default=2)
def main(file: Path, db_version) -> None:
    asyncio.run(run_sync_test(Path(file), db_version))


if __name__ == "__main__":
    # pylint: disable = no-value-for-parameter
    main()
