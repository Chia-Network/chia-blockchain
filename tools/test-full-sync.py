#!/usr/bin/env python3

import asyncio
import aiosqlite
import zstd
import click
import dataclasses
from pathlib import Path
from time import time

from chia.types.full_block import FullBlock
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from tests.util.db_connection import DBConnection
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.consensus.blockchain import Blockchain, ReceiveBlockResult


async def run_sync_test(file: Path, db_version=2) -> None:

    # use the mainnet genesis challenge
    constants = dataclasses.replace(
        DEFAULT_CONSTANTS,
        GENESIS_CHALLENGE=bytes.fromhex("ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb"),
    )

    counter = 0
    async with aiosqlite.connect(file) as in_db:
        async with DBConnection(db_version) as db_wrapper:
            coin_store = await CoinStore.create(db_wrapper)
            block_store = await BlockStore.create(db_wrapper)
            hint_store = await HintStore.create(db_wrapper)
            bc = await Blockchain.create(coin_store, block_store, constants, hint_store, file.parent, 0)

            rows = await in_db.execute("SELECT header_hash, height, block FROM full_blocks ORDER BY height")

            block_batch = []

            start_time = time()
            async for r in rows:
                block = FullBlock.from_bytes(zstd.decompress(r[2]))

                block_batch.append(block)
                if len(block_batch) < 32:
                    continue

                pre_validation_results = await bc.pre_validate_blocks_multiprocessing(
                    block_batch, {}, validate_signatures=False
                )
                assert len(pre_validation_results) > 0
                for pre_valid, block in zip(pre_validation_results, block_batch):
                    if pre_valid.error is not None:
                        print(f"block failed pre-validation: {pre_valid.error}")
                        return

                    added, error_code, fork_height, coin_changes = await bc.receive_block(block, pre_valid, None)
                    if added == ReceiveBlockResult.INVALID_BLOCK:
                        print(f"block failed: {error_code}")
                        return
                    assert added != ReceiveBlockResult.DISCONNECTED_BLOCK
                    assert added != ReceiveBlockResult.ALREADY_HAVE_BLOCK
                    counter += 1
                print(f"added {counter} {counter/(time() - start_time):0.2f} blocks/s")
                block_batch = []


@click.command()
@click.argument("file", type=click.Path(), required=True)
@click.argument("db-version", type=int, required=False, default=2)
def main(file: Path, db_version) -> None:
    asyncio.run(run_sync_test(Path(file), db_version))


if __name__ == "__main__":
    # pylint: disable = no-value-for-parameter
    main()
