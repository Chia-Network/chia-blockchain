import pytest

from typing import Tuple, Optional
from blspy import G2Element

from chia.clvm.singletons.singleton_drivers import adapt_inner_to_singleton
from chia.clvm.spend_sim import SpendSim, SimClient
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.ints import uint64, uint32
from chia.util.errors import Err
from chia.wallet.rl_wallet.rl_drivers import (
    create_rl_puzzle,
    create_rl_solution,
    uncurry_rl_puzzle,
)

from tests.clvm.benchmark_costs import cost_of_spend_bundle

"""
This test suite aims to test rl.clsp and rl_drivers.py

It is only meant to test the rate limiting outer puzzle and ignores all other puzzles that would normally be combined
with this one. It does not test any clawback features as that is a layer above, nor does it even bother to actually
make the coin a singleton, even though this is a puzzle that specifically expects to be inside a singleton.

For more comprehensive tests of the entire standard stack see the test_RL_wallet_lifecycle.py tests:
Singleton -> Shared Custody -> No melt -> RL -> <inner puzzle>
"""


class TestRlLifecycle:
    cost = {}

    @pytest.fixture(scope="function")
    async def setup(self):
        sim = await SpendSim.create()
        sim_client = SimClient(sim)

        adapted_puzzle: Program = adapt_inner_to_singleton(Program.to(1))
        adapted_ph: bytes32 = adapted_puzzle.get_tree_hash()
        rl_puzzle: Program = create_rl_puzzle(  # 500 mojos per block, cap of 10000, no initial credit, anyone can spend
            500, 1, 10000, 0, sim.block_height + 1, adapted_puzzle
        )
        rl_ph: bytes32 = rl_puzzle.get_tree_hash()
        await sim.farm_block(adapted_ph)
        farmed_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(adapted_ph))[0].coin
        # Gotta make it an odd amount
        starting_amount: uint64 = 10000005
        spend_bundle = SpendBundle(
            [CoinSpend(farmed_coin, adapted_puzzle, Program.to(([], [[51, rl_ph, starting_amount]])))],
            G2Element(),
        )
        await sim_client.push_tx(spend_bundle)
        await sim.farm_block()  # Our rate counter will be at 0 after this
        starting_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(rl_ph))[0].coin
        yield sim, sim_client, adapted_puzzle, adapted_ph, starting_coin, starting_amount, rl_puzzle, rl_ph

    async def spend_rl_coins(
        self, amount: uint64, blocks: uint32, setup
    ) -> Tuple[MempoolInclusionStatus, Optional[Err]]:
        sim, sim_client, adapted_puzzle, adapted_ph, starting_coin, starting_amount, rl_puzzle, rl_ph = setup
        for _ in range(0, blocks):
            await sim.farm_block()
        inner_solution = Program.to([[51, adapted_ph, uint64(starting_amount - amount)]])
        rl_solution = create_rl_solution(sim.block_height, inner_solution)
        fake_truths = Program.to(([], (([], starting_amount), [])))
        rl_solution = Program.to((fake_truths, rl_solution))  # Slight modification to account for Truths
        spend_bundle = SpendBundle(
            [
                CoinSpend(
                    starting_coin,
                    rl_puzzle,
                    rl_solution,
                )
            ],
            G2Element(),
        )
        self.cost["Cost for spend"] = cost_of_spend_bundle(spend_bundle)
        results = await sim_client.push_tx(spend_bundle)
        return results

    @pytest.mark.asyncio
    async def test_can_spend_amount_earned(self, setup):
        sim, sim_client, adapted_puzzle, adapted_ph, starting_coin, starting_amount, rl_puzzle, rl_ph = setup
        try:
            rl_info = uncurry_rl_puzzle(rl_puzzle)
            results = await self.spend_rl_coins(rl_info["amount_per"], rl_info["interval_time"], setup)
            assert results[0] == MempoolInclusionStatus.SUCCESS
        finally:
            await sim.close()

    @pytest.mark.asyncio
    async def test_cannot_spend_more_than_earned(self, setup):
        sim, sim_client, adapted_puzzle, adapted_ph, starting_coin, starting_amount, rl_puzzle, rl_ph = setup
        try:
            rl_info = uncurry_rl_puzzle(rl_puzzle)
            results = await self.spend_rl_coins(rl_info["amount_per"] + 1, rl_info["interval_time"], setup)
            assert results[0] == MempoolInclusionStatus.FAILED
            assert results[1] == Err.GENERATOR_RUNTIME_ERROR
        finally:
            await sim.close()

    @pytest.mark.asyncio
    async def test_cannot_spend_above_earnings_cap(self, setup):
        sim, sim_client, adapted_puzzle, adapted_ph, starting_coin, starting_amount, rl_puzzle, rl_ph = setup
        try:
            rl_info = uncurry_rl_puzzle(rl_puzzle)
            # Calculate the amount of blocks until we hit our earnings cap
            import math

            till_cap = math.floor(rl_info["interval_time"] * (rl_info["earnings_cap"] / rl_info["amount_per"]))
            results = await self.spend_rl_coins(rl_info["earnings_cap"] + 1, till_cap + 1, setup)
            assert results[0] == MempoolInclusionStatus.FAILED
            assert results[1] == Err.GENERATOR_RUNTIME_ERROR
        finally:
            await sim.close()

    @pytest.mark.asyncio
    async def test_can_use_credit_immediately(self, setup):
        sim, sim_client, adapted_puzzle, adapted_ph, starting_coin, starting_amount, rl_puzzle, rl_ph = setup
        try:
            rl_info = uncurry_rl_puzzle(rl_puzzle)
            results = await self.spend_rl_coins(rl_info["amount_per"], rl_info["interval_time"] * 2, setup)
            assert results[0] == MempoolInclusionStatus.SUCCESS

            await sim.farm_block()

            new_rl_puzzle: Program = create_rl_puzzle(
                rl_info["amount_per"],
                rl_info["interval_time"],
                rl_info["earnings_cap"],
                rl_info["credit"] + rl_info["amount_per"],
                (sim.block_height - 1),
                adapted_puzzle,
            )
            inner_solution = Program.to([[51, adapted_ph, uint64(starting_amount - (rl_info["amount_per"] * 2))]])
            fake_truths = Program.to(([], (([], starting_amount - rl_info["amount_per"]), [])))
            new_rl_solution = create_rl_solution(0, inner_solution)  # Should emulate an ephemeral spend too
            new_rl_solution = Program.to((fake_truths, new_rl_solution))  # Slight modification to account for Truths

            spend_bundle = SpendBundle(
                [
                    CoinSpend(
                        Coin(
                            starting_coin.name(),
                            new_rl_puzzle.get_tree_hash(),
                            starting_amount - rl_info["amount_per"],
                        ),
                        new_rl_puzzle,
                        new_rl_solution,
                    )
                ],
                G2Element(),
            )

            results = await sim_client.push_tx(spend_bundle)
            assert results[0] == MempoolInclusionStatus.SUCCESS

            await sim.farm_block()

            # We should check that the credit amount is back to what it used to be
            old_credit_puzzle: Program = create_rl_puzzle(
                rl_info["amount_per"],
                rl_info["interval_time"],
                rl_info["earnings_cap"],
                rl_info["credit"],
                uint32(sim.block_height - 2),
                adapted_puzzle,
            )
            assert (
                len(
                    (
                        await sim_client.get_coin_records_by_puzzle_hash(
                            old_credit_puzzle.get_tree_hash(),
                            include_spent_coins=False,
                        )
                    )
                )
                == 1
            )
        finally:
            await sim.close()

    def test_cost(self):
        import json
        import logging
        log = logging.getLogger(__name__)
        log.warning(json.dumps(self.cost))