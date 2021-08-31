import pytest

from typing import List
from blspy import G2Element

from chia.clvm.spend_sim import SpendSim, SimClient
from chia.clvm.taproot.merkle_tree import MerkleTree
from chia.clvm.singletons.singleton_drivers import adapt_inner_to_singleton
from chia.clvm.taproot.taproot_drivers import (
    create_taproot_puzzle,
    create_taproot_solution,
)
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.ints import uint64
from chia.util.errors import Err
from chia.util.hash import std_hash

from tests.clvm.benchmark_costs import cost_of_spend_bundle

"""
This file is intended to test:
    - chia.clvm.taproot.taproot_drivers
    - chia.clvm.taproot.merkle_tree
    - chia.clvm.taproot.puzzles.shared_custody.clsp

It is intended to be agnostic of all other puzzles, including singletons, even though this is designed
to be used underneath the singleton top layer.
"""


class TestSingletonTaproot:
    cost = {}

    @pytest.fixture(scope="function")
    async def setup(self):
        sim = await SpendSim.create()
        sim_client = SimClient(sim)

        anyone_can_spend = Program.to(1)
        acs_ph: bytes32 = anyone_can_spend.get_tree_hash()
        await sim.farm_block(acs_ph)
        farmed_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(acs_ph))[0].coin
        # Gotta make it an odd amount
        starting_amount: uint64 = 10000005
        spend_bundle = SpendBundle(
            [CoinSpend(farmed_coin, anyone_can_spend, Program.to([[51, acs_ph, starting_amount]]))],
            G2Element(),
        )
        await sim_client.push_tx(spend_bundle)
        await sim.farm_block()

        starting_coin: Coin = (await sim.all_non_reward_coins())[0]

        yield sim, sim_client, anyone_can_spend, acs_ph, starting_coin, starting_amount

    def generate_dummy_puzzles(self, num: int) -> List[Program]:
        final_list = []
        for i in range(0, num):
            # (c (list 60 0xdeadbeef) 1)
            final_list.append(adapt_inner_to_singleton(Program.to([4, (1, [60, std_hash(i)]), 1])))

        return final_list

    async def spend_all_puzzles(self, puzzle_list: List[Program], setup):
        sim, sim_client, anyone_can_spend, acs_ph, starting_coin, starting_amount = setup

        hash_list: List[bytes32] = [prog.get_tree_hash() for prog in puzzle_list]
        tree = MerkleTree(hash_list)

        taproot_puz: Program = create_taproot_puzzle(tree)
        taproot_ph: bytes32 = taproot_puz.get_tree_hash()

        spend_bundle = SpendBundle(
            [CoinSpend(starting_coin, anyone_can_spend, Program.to([[51, taproot_ph, starting_amount]]))], G2Element()
        )
        await sim_client.push_tx(spend_bundle)
        await sim.farm_block()

        next_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(taproot_ph))[0].coin
        total_cost = 0
        for puz in puzzle_list:
            inner_solution = Program.to([[51, puz.get_tree_hash(), starting_amount]])
            taproot_solution = create_taproot_solution(tree, puz, inner_solution)
            taproot_solution = Program.to(([], taproot_solution))  # Slight modification for "Truths"
            bundle = SpendBundle(
                [
                    CoinSpend(
                        next_coin,
                        taproot_puz,
                        taproot_solution,
                    )
                ],
                G2Element(),
            )
            total_cost += cost_of_spend_bundle(bundle)
            results = await sim_client.push_tx(bundle)
            assert results[0] == MempoolInclusionStatus.SUCCESS
            await sim.farm_block()

            next_coin = (
                await sim_client.get_coin_records_by_puzzle_hash(
                    taproot_ph,
                    include_spent_coins=False,
                )
            )[0].coin

        self.cost[f"Avg cost at depth {len(puzzle_list)}"] = total_cost/len(puzzle_list)

    @pytest.mark.asyncio
    async def test_one_puzzle(self, setup):
        sim, sim_client, anyone_can_spend, acs_ph, starting_coin, starting_amount = setup
        try:
            one_puzzle: List[bytes32] = self.generate_dummy_puzzles(1)
            await self.spend_all_puzzles(one_puzzle, setup)
        finally:
            await sim.close()

    @pytest.mark.asyncio
    async def test_two_puzzles(self, setup):
        sim, sim_client, anyone_can_spend, acs_ph, starting_coin, starting_amount = setup
        try:
            two_puzzles: List[bytes32] = self.generate_dummy_puzzles(2)
            await self.spend_all_puzzles(two_puzzles, setup)
        finally:
            await sim.close()

    @pytest.mark.asyncio
    async def test_ten_puzzles(self, setup):
        sim, sim_client, anyone_can_spend, acs_ph, starting_coin, starting_amount = setup
        try:
            ten_puzzles: List[bytes32] = self.generate_dummy_puzzles(10)
            await self.spend_all_puzzles(ten_puzzles, setup)
        finally:
            await sim.close()

    @pytest.mark.asyncio
    async def test_cannot_spend_extra_puzzle(self, setup):
        sim, sim_client, anyone_can_spend, acs_ph, starting_coin, starting_amount = setup
        try:
            some_puzzles: List[bytes32] = self.generate_dummy_puzzles(3)
            await self.spend_all_puzzles(some_puzzles[0:2], setup)

            next_coin: Coin = (await sim.all_non_reward_coins())[0]
            puz: Program = some_puzzles[2]
            tree = MerkleTree([prog.get_tree_hash() for prog in some_puzzles[0:2]])
            taproot_puz = create_taproot_puzzle(tree)
            inner_solution = Program.to([[51, puz.get_tree_hash(), starting_amount]])
            taproot_solution = create_taproot_solution(tree, puz, inner_solution)
            taproot_solution = Program.to(([], taproot_solution))  # Slight modification for Truths
            bundle = SpendBundle(
                [
                    CoinSpend(
                        next_coin,
                        taproot_puz,
                        taproot_solution,
                    )
                ],
                G2Element(),
            )
            results = await sim_client.push_tx(bundle)
            assert results[0] == MempoolInclusionStatus.FAILED
            assert results[1] == Err.GENERATOR_RUNTIME_ERROR

        finally:
            await sim.close()

    def test_cost(self):
        import json
        import logging
        log = logging.getLogger(__name__)
        log.warning(json.dumps(self.cost))
