import logging
from math import ceil
from typing import Any, List, Optional, Tuple

import pytest
from blspy import G2Element
from chia_rs import Coin
from clvm.casts import int_from_bytes

from chia.clvm.spend_sim import SimClient, SpendSim
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.wallet.puzzles.load_clvm import load_clvm

logging.getLogger("aiosqlite").setLevel(logging.INFO)  # Too much logging on debug level
FAKE_AMM_MOD: Program = load_clvm("fake_amm.clvm")
AGGREGATOR_MOD: Program = load_clvm("aggregator.clvm")
LOCK_MOD: Program = load_clvm("lock.clvm")
FEE_PUZ: Program = Program.to(1)


def get_deltas(puzzle: Program, a: Optional[int] = None, b: Optional[int] = None) -> Tuple[int, int]:
    assert b or a
    mod, params = puzzle.uncurry()
    token_a, token_b, K = [int_from_bytes(x) for x in params.as_atom_list()[1:]]

    token_a /= 10000
    K /= 10000
    token_b /= 10000
    if a:
        delta_withdraw = a
        delta_deposit = (K / (token_a + delta_withdraw)) - token_b
        delta_withdraw = ceil(delta_withdraw * 10000)
        delta_deposit = ceil(delta_deposit * 10000)
        return delta_withdraw, delta_deposit
    if b:
        # TODO: implement b case too
        raise NotImplementedError()
    return (-1, -1)


def get_amm_puzzle(w: int, d: int, puzzle: Program) -> Program:
    mod, params = puzzle.uncurry()
    token_a, token_b, K = [int_from_bytes(x) for x in params.as_atom_list()[1:]]
    return FAKE_AMM_MOD.curry(FAKE_AMM_MOD.get_tree_hash(), w + token_a, d + token_b, 2000000 * 10000)


@pytest.mark.asyncio()
async def test_aggregator_puzzle(setup_sim: Tuple[SpendSim, SimClient]) -> None:
    sim, sim_client = setup_sim

    try:
        fake_amm_puzzle: Program = FAKE_AMM_MOD.curry(
            FAKE_AMM_MOD.get_tree_hash(), 10000 * 10000, 200 * 10000, 2000000 * 10000
        )
        delta_withdraw, delta_deposit = get_deltas(fake_amm_puzzle, a=-1000)
        conds = fake_amm_puzzle.run([delta_withdraw, delta_deposit, []])
        updated_fake_amm_puzzle = get_amm_puzzle(delta_withdraw, delta_deposit, fake_amm_puzzle)
        assert bytes32(conds.at("frf").atom) == updated_fake_amm_puzzle.get_tree_hash()
        # main aggregator
        aggregator: Program = AGGREGATOR_MOD.curry(
            AGGREGATOR_MOD.get_tree_hash(), LOCK_MOD.get_tree_hash(), fake_amm_puzzle.get_tree_hash()
        )

        w, d = get_deltas(updated_fake_amm_puzzle, a=-2000)
        sol1 = [fake_amm_puzzle, [delta_withdraw, delta_deposit, []]]
        w1, d1 = get_deltas(updated_fake_amm_puzzle, a=-2000)
        sol2 = [updated_fake_amm_puzzle, [w1, d1, []]]
        solution = [sol1, sol2]
        conds = aggregator.run([1, solution])
        last_amm_puzzle = get_amm_puzzle(w, d, updated_fake_amm_puzzle)
        new_ph = AGGREGATOR_MOD.curry(
            AGGREGATOR_MOD.get_tree_hash(), LOCK_MOD.get_tree_hash(), last_amm_puzzle.get_tree_hash()
        ).get_tree_hash()
        assert bytes32(conds.at("frf").atom) == new_ph

    finally:
        await sim.close()


def make_agg_spendbundle(
    aggregator: Program,
    fee_coin: Coin,
    agg_coin: Coin,
    inner_puzzle: Program,
    orders: List[Any],
    fee: int = 0,
) -> SpendBundle:
    solutions = []
    spends = []
    pos = 1
    for order_tuple in orders:
        conditions: List[Any] = []
        if len(order_tuple) == 3:
            a, b, add_solution = order_tuple
        elif len(order_tuple) == 4:
            a, b, add_solution, conditions = order_tuple
        else:
            assert len(order_tuple) in (3, 4)
        delta_w, delta_d = get_deltas(inner_puzzle, a=a, b=b)
        new_puzzle = get_amm_puzzle(delta_w, delta_d, inner_puzzle)
        sol = [inner_puzzle, [delta_w, delta_d, conditions]]
        lock_puzzle = LOCK_MOD.curry(Program.to(sol).get_tree_hash(), pos)
        lock_spend = CoinSpend(
            Coin(agg_coin.name(), lock_puzzle.get_tree_hash(), 0), lock_puzzle, Program.to([agg_coin.name()])
        )
        spends.append(lock_spend)
        if add_solution:
            solutions.append(sol)
            inner_puzzle = new_puzzle
            pos += 1

    generic_spend = CoinSpend(
        agg_coin,
        aggregator,
        Program.to([1, solutions]),
    )
    if fee:
        fee_spend = CoinSpend(
            fee_coin, FEE_PUZ, Program.to([[51, FEE_PUZ.get_tree_hash(), fee_coin.amount - fee], [52, fee]])
        )
        spends.append(fee_spend)
    spends.append(generic_spend)
    generic_bundle = SpendBundle(spends, G2Element())
    return generic_bundle


@pytest.mark.asyncio()
async def test_aggregator_spend_basic(setup_sim: Tuple[SpendSim, SimClient]) -> None:
    sim, sim_client = setup_sim

    try:
        fake_amm_puzzle: Program = FAKE_AMM_MOD.curry(
            FAKE_AMM_MOD.get_tree_hash(), 10000 * 10000, 200 * 10000, 2000000 * 10000
        )
        # main aggregator
        aggregator: Program = AGGREGATOR_MOD.curry(
            AGGREGATOR_MOD.get_tree_hash(), LOCK_MOD.get_tree_hash(), fake_amm_puzzle.get_tree_hash()
        )

        # init coins
        await sim.farm_block(FEE_PUZ.get_tree_hash())
        fee_coin = (await sim_client.get_coin_records_by_puzzle_hash(FEE_PUZ.get_tree_hash()))[0].coin
        fee_spend = CoinSpend(
            fee_coin,
            FEE_PUZ,
            Program.to([[51, FEE_PUZ.get_tree_hash(), fee_coin.amount - 1], [51, aggregator.get_tree_hash(), 1]]),
        )
        await sim_client.push_tx(SpendBundle([fee_spend], G2Element()))
        await sim.farm_block(FEE_PUZ.get_tree_hash())
        fee_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(FEE_PUZ.get_tree_hash(), include_spent_coins=False)
        )[0].coin
        amm_ph = aggregator.get_tree_hash()
        amm_coin = (await sim_client.get_coin_records_by_puzzle_hash(amm_ph, include_spent_coins=False))[0].coin

        # start with 2 orders
        ssa_bundle = make_agg_spendbundle(
            aggregator, fee_coin, amm_coin, fake_amm_puzzle, [[-1000, None, True], [-2000, None, True]]
        )
        result = await sim_client.push_tx(ssa_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # try adding it with same fee, should fail
        ssa_bundle = make_agg_spendbundle(
            aggregator,
            fee_coin,
            amm_coin,
            fake_amm_puzzle,
            [[-1000, None, True], [-2000, None, True], [-500, None, True]],
        )
        result = await sim_client.push_tx(ssa_bundle)
        assert result == (MempoolInclusionStatus.PENDING, Err.MEMPOOL_CONFLICT)

        # increase fee by 10000000, should go through
        ssa_bundle = make_agg_spendbundle(
            aggregator,
            fee_coin,
            amm_coin,
            fake_amm_puzzle,
            [[-1000, None, True], [-2000, None, True], [-500, None, True]],
            fee=10000000,
        )
        result = await sim_client.push_tx(ssa_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
    finally:
        await sim.close()


@pytest.mark.asyncio()
async def test_aggregator_spend_attacks(setup_sim: Tuple[SpendSim, SimClient]) -> None:
    sim, sim_client = setup_sim

    try:
        fake_amm_puzzle: Program = FAKE_AMM_MOD.curry(
            FAKE_AMM_MOD.get_tree_hash(), 10000 * 10000, 200 * 10000, 2000000 * 10000
        )
        # main aggregator
        aggregator: Program = AGGREGATOR_MOD.curry(
            AGGREGATOR_MOD.get_tree_hash(), LOCK_MOD.get_tree_hash(), fake_amm_puzzle.get_tree_hash()
        )

        # init coins
        await sim.farm_block(FEE_PUZ.get_tree_hash())
        fee_coin = (await sim_client.get_coin_records_by_puzzle_hash(FEE_PUZ.get_tree_hash()))[0].coin
        fee_spend = CoinSpend(
            fee_coin,
            FEE_PUZ,
            Program.to([[51, FEE_PUZ.get_tree_hash(), fee_coin.amount - 1], [51, aggregator.get_tree_hash(), 1]]),
        )
        await sim_client.push_tx(SpendBundle([fee_spend], G2Element()))
        await sim.farm_block(FEE_PUZ.get_tree_hash())
        fee_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(FEE_PUZ.get_tree_hash(), include_spent_coins=False)
        )[0].coin
        amm_ph = aggregator.get_tree_hash()
        amm_coin = (await sim_client.get_coin_records_by_puzzle_hash(amm_ph, include_spent_coins=False))[0].coin

        ssa_bundle = make_agg_spendbundle(
            aggregator, fee_coin, amm_coin, fake_amm_puzzle, [[-1000, None, True], [-2000, None, True]]
        )
        result = await sim_client.push_tx(ssa_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # change order now, see if we get in
        ssa_bundle = make_agg_spendbundle(
            aggregator, fee_coin, amm_coin, fake_amm_puzzle, [[-2000, None, True], [-1000, None, True]], fee=10000000
        )
        result = await sim_client.push_tx(ssa_bundle)
        assert result == (MempoolInclusionStatus.PENDING, Err.MEMPOOL_CONFLICT)

        # remove a solution, keep the lock coin to test integrity
        ssa_bundle = make_agg_spendbundle(
            aggregator, fee_coin, amm_coin, fake_amm_puzzle, [[-1000, None, False], [-2000, None, True]], fee=10000000
        )
        result = await sim_client.push_tx(ssa_bundle)
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

    finally:
        await sim.close()
