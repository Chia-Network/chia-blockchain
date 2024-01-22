from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import List, Optional

import aiosqlite
import click

from chia.consensus.blockchain import Blockchain
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_version import lookup_db_version
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32

# the first transaction block. Each byte in transaction_height_delta is the
# number of blocks to skip forward to get to the next transaction block
transaction_block_heights = []
last = 225698
file_path = os.path.realpath(__file__)
for delta in open(Path(file_path).parent / "transaction_height_delta", "rb").read():
    new = last + delta
    transaction_block_heights.append(new)
    last = new


@dataclass(frozen=True)
class BlockInfo:
    prev_header_hash: bytes32
    transactions_generator: Optional[SerializedProgram]
    transactions_generator_ref_list: List[uint32]


def random_refs() -> List[uint32]:
    ret = random.sample(transaction_block_heights, DEFAULT_CONSTANTS.MAX_GENERATOR_REF_LIST_SIZE)
    random.shuffle(ret)
    return [uint32(i) for i in ret]


REPETITIONS = 100


async def main(db_path: Path) -> None:
    random.seed(0x213FB154)

    async with aiosqlite.connect(db_path) as connection:
        await connection.execute("pragma journal_mode=wal")
        await connection.execute("pragma synchronous=FULL")
        await connection.execute("pragma query_only=ON")
        db_version: int = await lookup_db_version(connection)

        db_wrapper = DBWrapper2(connection, db_version=db_version)
        await db_wrapper.add_connection(await aiosqlite.connect(db_path))

        block_store = await BlockStore.create(db_wrapper)
        coin_store = await CoinStore.create(db_wrapper)

        start_time = monotonic()
        # make configurable
        reserved_cores = 4
        blockchain = await Blockchain.create(coin_store, block_store, DEFAULT_CONSTANTS, db_path.parent, reserved_cores)

        peak = blockchain.get_peak()
        assert peak is not None
        timing = 0.0
        for i in range(REPETITIONS):
            block = BlockInfo(
                peak.header_hash,
                SerializedProgram.from_bytes(bytes.fromhex("80")),
                random_refs(),
            )

            start_time = monotonic()
            gen = await blockchain.get_block_generator(block)
            one_call = monotonic() - start_time
            timing += one_call
            assert gen is not None

        print(f"get_block_generator(): {timing/REPETITIONS:0.3f}s")

        blockchain.shut_down()


@click.command()
@click.argument("db-path", type=click.Path())
def entry_point(db_path: Path) -> None:
    asyncio.run(main(Path(db_path)))


if __name__ == "__main__":
    # pylint: disable = no-value-for-parameter
    entry_point()
