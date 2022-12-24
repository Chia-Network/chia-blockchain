from __future__ import annotations

import asyncio
import cProfile
from contextlib import contextmanager
from subprocess import check_call
from time import monotonic
from typing import Iterator, List

from utils import setup_db

from chia.consensus.block_record import BlockRecord
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.coin_store import CoinStore
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32, bytes100
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint8, uint32, uint64, uint128

NUM_ITERS = 100
NUM_PEERS = 5


@contextmanager
def enable_profiler(profile: bool, name: str) -> Iterator[None]:
    if not profile:
        yield
        return

    with cProfile.Profile() as pr:
        yield

    pr.create_stats()
    output_file = f"mempool-{name}"
    pr.dump_stats(output_file + ".profile")
    check_call(["gprof2dot", "-f", "pstats", "-o", output_file + ".dot", output_file + ".profile"])
    with open(output_file + ".png", "w+") as f:
        check_call(["dot", "-T", "png", output_file + ".dot"], stdout=f)
    print("output written to: %s.png" % output_file)


def fake_block_record(block_height: uint32, timestamp: uint64) -> BlockRecord:
    return BlockRecord(
        bytes32(b"a" * 32),  # header_hash
        bytes32(b"b" * 32),  # prev_hash
        block_height,  # height
        uint128(0),  # weight
        uint128(0),  # total_iters
        uint8(0),  # signage_point_index
        ClassgroupElement(bytes100(b"1" * 100)),  # challenge_vdf_output
        None,  # infused_challenge_vdf_output
        bytes32(b"f" * 32),  # reward_infusion_new_challenge
        bytes32(b"c" * 32),  # challenge_block_info_hash
        uint64(0),  # sub_slot_iters
        bytes32(b"d" * 32),  # pool_puzzle_hash
        bytes32(b"e" * 32),  # farmer_puzzle_hash
        uint64(0),  # required_iters
        uint8(0),  # deficit
        False,  # overflow
        uint32(block_height - 1),  # prev_transaction_block_height
        timestamp,  # timestamp
        None,  # prev_transaction_block_hash
        uint64(0),  # fees
        None,  # reward_claims_incorporated
        None,  # finished_challenge_slot_hashes
        None,  # finished_infused_challenge_slot_hashes
        None,  # finished_reward_slot_hashes
        None,  # sub_epoch_summary_included
    )


async def run_mempool_benchmark(single_threaded: bool) -> None:

    suffix = "st" if single_threaded else "mt"
    db_wrapper: DBWrapper2 = await setup_db(f"mempool-benchmark-coins-{suffix}.db", 2)

    try:
        coin_store = await CoinStore.create(db_wrapper)
        mempool = MempoolManager(coin_store.get_coin_record, DEFAULT_CONSTANTS, single_threaded=single_threaded)

        wt = WalletTool(DEFAULT_CONSTANTS)

        spend_bundles: List[List[SpendBundle]] = []

        timestamp = uint64(1631794488)

        height = uint32(1)

        print("Building SpendBundles")
        for peer in range(NUM_PEERS):

            print(f"  peer {peer}")
            print("     reward coins")
            unspent: List[Coin] = []
            for idx in range(NUM_ITERS):
                height = uint32(height + 1)
                # farm rewards
                farmer_coin = create_farmer_coin(
                    height, wt.get_new_puzzlehash(), uint64(250000000), DEFAULT_CONSTANTS.GENESIS_CHALLENGE
                )
                pool_coin = create_pool_coin(
                    height, wt.get_new_puzzlehash(), uint64(1750000000), DEFAULT_CONSTANTS.GENESIS_CHALLENGE
                )
                unspent.extend([farmer_coin, pool_coin])
                await coin_store.new_block(
                    height,
                    timestamp,
                    set([pool_coin, farmer_coin]),
                    [],
                    [],
                )

            bundles: List[SpendBundle] = []

            print("     spend bundles")
            for coin in unspent:
                tx: SpendBundle = wt.generate_signed_transaction(
                    uint64(coin.amount // 2), wt.get_new_puzzlehash(), coin
                )
                bundles.append(tx)
            spend_bundles.append(bundles)

            # 19 seconds per block
            timestamp = uint64(timestamp + 19)

        if single_threaded:
            print("Single-threaded")
        else:
            print("Multi-threaded")
        print("Profiling add_spendbundle()")

        # the mempool only looks at:
        #   timestamp
        #   height
        #   is_transaction_block
        #   header_hash
        print("initialize MempoolManager")
        rec = fake_block_record(height, timestamp)
        await mempool.new_peak(rec, None)

        async def add_spend_bundles(spend_bundles: List[SpendBundle]) -> None:
            for tx in spend_bundles:
                spend_bundle_id = tx.name()
                npc = await mempool.pre_validate_spendbundle(tx, None, spend_bundle_id)
                assert npc is not None
                _, status, error = await mempool.add_spend_bundle(tx, npc, spend_bundle_id, height)
                assert status == MempoolInclusionStatus.SUCCESS
                assert error is None

        total_bundles = 0
        tasks = []
        with enable_profiler(True, f"add-{suffix}"):
            start = monotonic()
            for peer in range(NUM_PEERS):
                total_bundles += len(spend_bundles[peer])
                tasks.append(asyncio.create_task(add_spend_bundles(spend_bundles[peer])))
            await asyncio.gather(*tasks)
            stop = monotonic()
        print(f"add_spendbundle time: {stop - start:0.4f}s")
        print(f"{(stop - start) / total_bundles * 1000:0.2f}ms per add_spendbundle() call")

        with enable_profiler(True, f"create-{suffix}"):
            start = monotonic()
            for _ in range(2000):
                mempool.create_bundle_from_mempool(bytes32(b"a" * 32))
            stop = monotonic()
        print(f"create_bundle_from_mempool time: {stop - start:0.4f}s")

    # TODO: add benchmark for new_peak()

    finally:
        await db_wrapper.close()


if __name__ == "__main__":
    import logging

    logger = logging.getLogger()
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.WARNING)
    asyncio.run(run_mempool_benchmark(True))
    asyncio.run(run_mempool_benchmark(False))
