from __future__ import annotations

import dataclasses
import logging
from typing import Callable, List, Optional, Tuple

import pytest
from chia_rs import Coin, G2Element

from chia.clvm.spend_sim import SimClient, SpendSim, sim_and_client
from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bitcoin_fee_estimator import BitcoinFeeEstimator
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.spend_bundle import SpendBundle

log = logging.getLogger(__name__)

the_puzzle_hash = bytes32(
    bytes.fromhex("9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2")
)  # Program.to(1)

NEW_DEFAULT_CONSTANTS: ConsensusConstants = dataclasses.replace(
    DEFAULT_CONSTANTS,
    MAX_BLOCK_COST_CLVM=300000000,
    MEMPOOL_BLOCK_BUFFER=1,
)


async def farm(
    sim: SpendSim,
    puzzle_hash: bytes32,
    item_inclusion_filter: Optional[Callable[[bytes32], bool]] = None,
) -> Tuple[List[Coin], List[Coin], List[Coin]]:
    additions, removals = await sim.farm_block(puzzle_hash)  # , item_inclusion_filter)
    height = sim.get_height()
    new_reward_coins = sim.block_records[height].reward_claims_incorporated
    return additions, removals, new_reward_coins


def make_tx_sb(from_coin: Coin) -> SpendBundle:
    coin_spend = make_spend(
        from_coin,
        Program.to(1),
        Program.to([[51, from_coin.puzzle_hash, from_coin.amount]]),
    )
    spend_bundle = SpendBundle([coin_spend], G2Element())
    return spend_bundle


async def init_test(
    sim: SpendSim, cli: SimClient, puzzle_hash: bytes32, spends_per_block: int
) -> Tuple[BitcoinFeeEstimator, List[Coin], List[Coin]]:
    new_reward_coins = []
    spend_coins = []
    fee_coins = []
    await farm(sim, puzzle_hash)

    for i in range(1, spends_per_block + 1):
        await farm(sim, puzzle_hash)
        new_reward_coins.extend(sim.block_records[i].reward_claims_incorporated)
        fee_coins.append(sim.block_records[i].reward_claims_incorporated[0])
        spend_coins.append(sim.block_records[i].reward_claims_incorporated[1])
    await farm(sim, puzzle_hash)

    assert len(sim.blocks) == spends_per_block + 2
    assert sim.blocks[-1].height == spends_per_block + 1
    assert sim.block_records[0].reward_claims_incorporated[0].amount == 18375000000000000000
    assert sim.block_records[0].reward_claims_incorporated[1].amount == 2625000000000000000

    assert sim.block_records[1].reward_claims_incorporated[0].amount == 1750000000000
    assert sim.block_records[1].reward_claims_incorporated[1].amount == 250000000000

    estimator: BitcoinFeeEstimator = sim.mempool_manager.mempool.fee_estimator  # type:ignore
    return estimator, spend_coins, fee_coins  # new_reward_coins


@pytest.mark.anyio
async def test_mempool_inclusion_filter_basic() -> None:
    async with sim_and_client(defaults=NEW_DEFAULT_CONSTANTS, pass_prefarm=False) as (sim, cli):
        estimator, spend_coins, fee_coins = await init_test(sim, cli, the_puzzle_hash, 1)
        assert sim.mempool_manager.mempool.size() == 0

        spend_bundle: SpendBundle = make_tx_sb(spend_coins[0])
        status, error = await cli.push_tx(spend_bundle)
        assert sim.mempool_manager.mempool.size() == 1
        assert error is None

        mempool_item = sim.mempool_manager.get_mempool_item(spend_bundle.name())
        assert mempool_item

        def include_none(bundle_name: bytes32) -> bool:
            return False

        def include_all(bundle_name: bytes32) -> bool:
            return True

        additions, removals = await sim.farm_block(the_puzzle_hash, item_inclusion_filter=include_none)
        assert sim.mempool_manager.mempool.size() == 1
        assert removals == []

        additions, removals = await sim.farm_block(the_puzzle_hash, item_inclusion_filter=include_all)
        assert sim.mempool_manager.mempool.size() == 0
        removal_ids = [c.name() for c in removals]
        assert mempool_item.name not in removal_ids


@pytest.mark.anyio
async def test_mempoolitem_height_added(db_version: int) -> None:
    async with sim_and_client(defaults=NEW_DEFAULT_CONSTANTS, pass_prefarm=False) as (sim, cli):
        estimator, spend_coins, fee_coins = await init_test(sim, cli, the_puzzle_hash, 1)
        assert sim.mempool_manager.mempool.size() == 0

        spend_bundle: SpendBundle = make_tx_sb(spend_coins[0])

        status, error = await cli.push_tx(spend_bundle)
        assert sim.mempool_manager.mempool.size() == 1
        log.warning(f"{status, error} = cli.push_tx({spend_bundle.name()})")

        mempool_item = sim.mempool_manager.get_mempool_item(spend_bundle.name())
        assert mempool_item
        heights = {sim.get_height(): mempool_item.height_added_to_mempool}

        def ignore_spend(bundle_name: bytes32) -> bool:
            assert mempool_item
            return bundle_name != mempool_item.name

        additions, removals = await sim.farm_block(the_puzzle_hash, item_inclusion_filter=ignore_spend)
        removal_ids = [c.name() for c in removals]
        assert mempool_item.name not in removal_ids

        mempool_item2 = sim.mempool_manager.get_mempool_item(spend_bundle.name())
        assert sim.mempool_manager.mempool.size() == 1
        assert mempool_item2

        # This is the important check in this test: ensure height_added_to_mempool does not
        # change when the mempool is rebuilt
        assert mempool_item2.height_added_to_mempool == mempool_item2.height_added_to_mempool

        # Now farm it into the next block
        additions, removals = await sim.farm_block(the_puzzle_hash)
        assert sim.mempool_manager.mempool.size() == 0
        assert len(removals) == 1

        log.warning(heights)
