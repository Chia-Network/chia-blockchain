from __future__ import annotations

import re
from dataclasses import replace

import pytest
from chia_rs import CoinSpend, G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.util.spend_sim import CostLogger, SimClient, SpendSim, sim_and_client
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.errors import Err
from chia.wallet.conditions import Condition, CreateCoin
from chia.wallet.puzzles.puzzle_drivers import DelegatedPuzzleAndSolution, UnknownPuzzle, UnknownSolution
from chia.wallet.puzzles.singleton_drivers import (
    P2Singleton,
    P2SingletonPuzzle,
    Singleton,
    SingletonLaunchInfo,
    SingletonPuzzle,
)
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

ACS = UnknownPuzzle(known_puzzle=Program.to(1))
ACS_PH = ACS.puzzle_hash


class TransactionPushError(Exception):
    pass


async def push_bundle(
    sim: SpendSim,
    sim_client: SimClient,
    spends: list[CoinSpend],
    ex_error: Err | None = None,
    fail_msg: str = "",
    cost_logger: CostLogger | None = None,
    cost_log_msg: str = "",
) -> None:
    spend_bundle = WalletSpendBundle(spends, G2Element())
    if cost_logger is not None:
        spend_bundle = cost_logger.add_cost(cost_log_msg, spend_bundle)

    try:
        _result, error = await sim_client.push_tx(spend_bundle)
        if error is None:
            await sim.farm_block()
        elif ex_error is not None:
            assert error == ex_error
        else:
            raise TransactionPushError(error)
    except AssertionError:
        raise AssertionError(fail_msg)


async def acs_fee_spend(sim_client: SimClient) -> CoinSpend:
    """Non-FF companion spend so solo singleton (FF) spends are mempool-valid."""
    records = await sim_client.get_coin_records_by_puzzle_hash(ACS_PH, include_spent_coins=False)
    fee_coin = next(record.coin for record in records if record.coin.amount % 2 == 0)
    return make_spend(
        fee_coin,
        ACS.puzzle,
        Program.to([[ConditionOpcode.CREATE_COIN, ACS_PH, fee_coin.amount - 10]]),
    )


async def odd_singleton_coin(sim: SpendSim) -> Coin:
    odds = [coin for coin in await sim.all_non_reward_coins() if coin.amount % 2 == 1]
    assert len(odds) == 1
    return odds[0]


def recreate_inner_solution(amount: uint64, *extra_conditions: Condition) -> UnknownSolution:
    return UnknownSolution(
        Program.to(
            [
                CreateCoin(puzzle_hash=ACS_PH, amount=amount).to_program(),
                *[condition.to_program() for condition in extra_conditions],
            ]
        )
    )


@pytest.mark.anyio
async def test_singleton_top_layer(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, sim_client):
        START_AMOUNT = uint64(1023)
        await sim.farm_block(ACS_PH)
        starting_coin = (await sim_client.get_coin_records_by_puzzle_hash(ACS_PH, include_spent_coins=False))[0].coin

        # LAUNCHING
        with pytest.raises(ValueError, match=re.escape("Coin amount cannot be even. Subtract one mojo.")):
            SingletonLaunchInfo(desired_inner_puzzle=ACS, key_value_hints={}, amount=uint64(2))
        launch_result = Singleton.launch(
            origin_coin=starting_coin,
            launch_info=SingletonLaunchInfo(
                desired_inner_puzzle=ACS, key_value_hints={"hello": "world"}, amount=START_AMOUNT
            ),
        )

        starting_spend = make_spend(
            starting_coin, ACS.puzzle, Program.to([cond.to_program() for cond in launch_result.necessary_conditions])
        )
        await push_bundle(
            sim,
            sim_client,
            [starting_spend, launch_result.launcher_spend],
            cost_logger=cost_logger,
            cost_log_msg="Singleton Launch + ACS",
        )

        # EVE
        singleton_eve = launch_result.launched_singleton
        assert singleton_eve.coin == await odd_singleton_coin(sim)

        singleton_eve_spend, singleton = singleton_eve.action_spend(recreate_inner_solution(singleton_eve.coin.amount))
        await push_bundle(
            sim,
            sim_client,
            [singleton_eve_spend],
            cost_logger=cost_logger,
            cost_log_msg="Singleton Eve Spend w/ ACS",
        )
        singleton.inner_puzzle = ACS

        await sim.farm_block(ACS_PH)  # for non-FF spends

        # POST-EVE
        assert singleton.coin == await odd_singleton_coin(sim)
        singleton_spend, singleton = singleton.action_spend(recreate_inner_solution(singleton.coin.amount))
        await push_bundle(
            sim,
            sim_client,
            [singleton_spend, await acs_fee_spend(sim_client)],
            cost_logger=cost_logger,
            cost_log_msg="Singleton Spend + ACS",
        )
        singleton.inner_puzzle = ACS

        # CLAIM A P2_SINGLETON
        assert singleton.coin == await odd_singleton_coin(sim)
        p2_singleton_puz = P2SingletonPuzzle(singleton_id=singleton.launcher_id)
        await sim.farm_block(p2_singleton_puz.puzzle_hash)
        p2_singleton_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(p2_singleton_puz.puzzle_hash, include_spent_coins=False)
        )[0].coin
        p2_singleton = P2Singleton(coin=p2_singleton_coin, singleton_id=singleton.launcher_id)
        p2_singleton_spends, messages = singleton.claim_p2_singletons(
            rewards_to_claim=[p2_singleton],
            reward_delegated_puzzles_and_solutions=[
                DelegatedPuzzleAndSolution(
                    puzzle=ACS,
                    solution=UnknownSolution(
                        solution=Program.to([CreateCoin(puzzle_hash=bytes32.zeros, amount=uint64(0)).to_program()])
                    ),
                )
            ],
        )
        singleton_claim_spend, singleton = singleton.action_spend(
            recreate_inner_solution(singleton.coin.amount, *messages)
        )
        await push_bundle(
            sim,
            sim_client,
            [singleton_claim_spend, *p2_singleton_spends],
            cost_logger=cost_logger,
            cost_log_msg="Singleton w/ ACS claim p2_singleton",
        )
        singleton.inner_puzzle = ACS
        assert len(await sim_client.get_coin_records_by_puzzle_hash(bytes32.zeros, include_spent_coins=False)) == 1

        # CREATE MULTIPLE ODD CHILDREN (Negative Test)
        singleton_coin = await odd_singleton_coin(sim)
        assert singleton_coin == singleton.coin
        multi_odd_spend, _ = singleton.action_spend(
            UnknownSolution(
                solution=Program.to(
                    [
                        [ConditionOpcode.CREATE_COIN, ACS_PH, 3],
                        [ConditionOpcode.CREATE_COIN, ACS_PH, 7],
                    ]
                )
            )
        )
        await push_bundle(
            sim,
            sim_client,
            [multi_odd_spend, await acs_fee_spend(sim_client)],
            ex_error=Err.GENERATOR_RUNTIME_ERROR,
            fail_msg="Too many odd children were allowed",
        )

        # CREATE NO ODD CHILDREN (Negative Test)
        no_odd_spend = singleton.spend(
            UnknownSolution(
                solution=Program.to(
                    [
                        [ConditionOpcode.CREATE_COIN, ACS_PH, 4],
                        [ConditionOpcode.CREATE_COIN, ACS_PH, 10],
                    ]
                )
            )
        )
        await push_bundle(
            sim,
            sim_client,
            [no_odd_spend, await acs_fee_spend(sim_client)],
            ex_error=Err.GENERATOR_RUNTIME_ERROR,
            fail_msg="Need at least one odd child",
        )

        # ATTEMPT TO CREATE AN EVEN SINGLETON (Negative test)
        save_height = sim.block_height
        singleton_even_spend, _ = singleton.action_spend(
            UnknownSolution(
                solution=Program.to(
                    [
                        [ConditionOpcode.CREATE_COIN, singleton.coin.puzzle_hash, 2],
                        [ConditionOpcode.CREATE_COIN, ACS_PH, 1],
                    ]
                )
            )
        )
        await push_bundle(sim, sim_client, [singleton_even_spend, await acs_fee_spend(sim_client)])

        # Now try a perfectly innocent spend
        evil_coin = next(filter(lambda c: c.amount == 2, await sim.all_non_reward_coins()))
        evil_singleton = Singleton(
            coin=evil_coin,
            launcher_id=singleton.launcher_id,
            inner_puzzle=ACS,
            lineage_proof=replace(singleton.lineage_proof, amount=uint64(2)),
        )
        evil_spend, _ = evil_singleton.action_spend(
            UnknownSolution(solution=Program.to([[ConditionOpcode.CREATE_COIN, ACS_PH, 1]]))
        )
        await push_bundle(
            sim,
            sim_client,
            [evil_spend, await acs_fee_spend(sim_client)],
            ex_error=Err.GENERATOR_RUNTIME_ERROR,
            fail_msg="This coin is even!",
        )

        # MELTING
        await sim.rewind(save_height)
        melt_spend = singleton.spend(
            UnknownSolution(
                solution=Program.to(
                    [
                        SingletonPuzzle.melt_condition.to_program(),
                        [ConditionOpcode.CREATE_COIN, ACS_PH, singleton.coin.amount - 1],
                    ]
                )
            )
        )
        await push_bundle(
            sim,
            sim_client,
            [melt_spend, await acs_fee_spend(sim_client)],
            cost_logger=cost_logger,
            cost_log_msg="Singleton w/ ACS melt",
        )

        melted_coin = next(
            coin
            for coin in await sim.all_non_reward_coins()
            if coin.puzzle_hash == ACS_PH and coin.amount == START_AMOUNT - 1
        )
        assert melted_coin.puzzle_hash == ACS_PH
