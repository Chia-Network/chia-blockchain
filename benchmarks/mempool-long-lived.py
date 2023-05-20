from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Dict, Optional

from blspy import G2Element
from clvm.casts import int_to_bytes

from chia.consensus.cost_calculator import NPCResult
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.mempool_manager import MempoolManager
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.types.spend_bundle_conditions import Spend, SpendBundleConditions
from chia.util.ints import uint32, uint64

# this is one week worth of blocks
NUM_ITERS = 32256


def make_hash(height: int) -> bytes32:
    return bytes32(height.to_bytes(32, byteorder="big"))


@dataclass(frozen=True)
class BenchBlockRecord:
    """
    This is a subset of BlockRecord that the mempool manager uses for peak.
    """

    header_hash: bytes32
    height: uint32
    timestamp: Optional[uint64]
    prev_transaction_block_height: uint32
    prev_transaction_block_hash: Optional[bytes32]

    @property
    def is_transaction_block(self) -> bool:
        return self.timestamp is not None


IDENTITY_PUZZLE = Program.to(1)
IDENTITY_PUZZLE_HASH = IDENTITY_PUZZLE.get_tree_hash()


def make_spend_bundle(coin: Coin, height: int) -> SpendBundle:
    # the fees we pay will go up over time (by subtracting height * 10)
    conditions = [
        [
            ConditionOpcode.CREATE_COIN,
            make_hash(height + coin.amount - 1),
            int_to_bytes(coin.amount // 2 - height * 10),
        ],
        [
            ConditionOpcode.CREATE_COIN,
            make_hash(height + coin.amount + 1),
            int_to_bytes(coin.amount // 2 - height * 10),
        ],
    ]
    spend = CoinSpend(coin, IDENTITY_PUZZLE, Program.to(conditions))
    return SpendBundle([spend], G2Element())


def fake_block_record(block_height: uint32, timestamp: uint64) -> BenchBlockRecord:
    this_hash = make_hash(block_height)
    prev_hash = make_hash(block_height - 1)
    return BenchBlockRecord(
        header_hash=this_hash,
        height=block_height,
        timestamp=timestamp,
        prev_transaction_block_height=uint32(block_height - 1),
        prev_transaction_block_hash=prev_hash,
    )


async def run_mempool_benchmark() -> None:
    coin_records: Dict[bytes32, CoinRecord] = {}

    async def get_coin_record(coin_id: bytes32) -> Optional[CoinRecord]:
        return coin_records.get(coin_id)

    timestamp = uint64(1631794488)

    mempool = MempoolManager(get_coin_record, DEFAULT_CONSTANTS, single_threaded=True)

    print("\nrunning add_spend_bundle() + new_peak()")

    start = monotonic()
    most_recent_coin_id = make_hash(100)
    for height in range(1, NUM_ITERS):
        timestamp = uint64(timestamp + 19)
        rec = fake_block_record(uint32(height), timestamp)
        # the new block spends on coind, the most recently added one
        # most_recent_coin_id
        npc_result = NPCResult(
            None,
            SpendBundleConditions(
                [Spend(most_recent_coin_id, bytes32(b" " * 32), None, 0, None, None, None, None, [], [], 0)],
                0,
                0,
                0,
                None,
                None,
                [],
                0,
                0,
                0,
            ),
            uint64(1000000000),
        )
        await mempool.new_peak(rec, npc_result)

        # add 10 transactions to the mempool
        for i in range(10):
            coin = Coin(make_hash(height * 10 + i), IDENTITY_PUZZLE_HASH, height * 100000 + i * 100)
            sb = make_spend_bundle(coin, height)
            # make this coin available via get_coin_record, which is called
            # by mempool_manager
            coin_records = {
                coin.name(): CoinRecord(coin, uint32(height // 2), uint32(0), False, uint64(timestamp // 2))
            }
            spend_bundle_id = sb.name()
            npc = await mempool.pre_validate_spendbundle(sb, None, spend_bundle_id)
            assert npc is not None
            await mempool.add_spend_bundle(sb, npc, spend_bundle_id, uint32(height))

        if height % 100 == 0:
            print(
                "height: ", height, " size: ", mempool.mempool.size(), " cost: ", mempool.mempool.total_mempool_cost()
            )
        # this coin will be spent in the next block
        most_recent_coin_id = coin.name()

    stop = monotonic()

    print(f"  time: {stop - start:0.4f}s")
    print(f"  per block: {(stop - start) / height * 1000:0.2f}ms")


if __name__ == "__main__":
    import logging

    logger = logging.getLogger()
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.WARNING)
    asyncio.run(run_mempool_benchmark())
