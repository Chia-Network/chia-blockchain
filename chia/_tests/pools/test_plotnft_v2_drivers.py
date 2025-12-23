from __future__ import annotations

from dataclasses import replace
from typing import Literal

import pytest
from chia_rs import G2Element, PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.clvm.test_puzzles import secret_exponent_for_index
from chia._tests.util.spend_sim import CostLogger, SimClient, SpendSim, sim_and_client
from chia.pools.plotnft_drivers import (
    PlotNFT,
    PoolConfig,
    PoolReward,
    RewardPuzzle,
    UserConfig,
)
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.wallet.conditions import AssertSecondsRelative, CreateCoin, MessageParticipant, SendMessage
from chia.wallet.puzzles.custody.custody_architecture import DelegatedPuzzleAndSolution
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
)
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

user_sk = calculate_synthetic_secret_key(
    PrivateKey.from_bytes(
        secret_exponent_for_index(1).to_bytes(32, "big"),
    ),
    DEFAULT_HIDDEN_PUZZLE_HASH,
)
ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()
POOL_PUZZLE = Program.to("I'm a pool :)")
POOL_PUZZLE_HASH = POOL_PUZZLE.get_tree_hash()


async def mint_plotnft(
    *, sim: SpendSim, sim_client: SimClient, desired_state: Literal["self_custody", "pooling", "waiting_room"]
) -> PlotNFT:
    await sim.farm_block(ACS_PH)

    [fund_coin, _] = await sim_client.get_coin_records_by_puzzle_hash(ACS_PH, include_spent_coins=False)

    # TODO: test extra_conditions and fee
    conditions, spends, plotnft = PlotNFT.launch(
        origin_coins=[fund_coin.coin],
        user_config=UserConfig(synthetic_pubkey=user_sk.get_g1()),
        pool_config=PoolConfig()
        if desired_state == "self_custody"
        else PoolConfig(pool_puzzle_hash=POOL_PUZZLE_HASH, timelock=uint64(1000)),
        genesis_challenge=sim.defaults.GENESIS_CHALLENGE,
        exiting=desired_state == "waiting_room",
    )

    result = await sim_client.push_tx(
        WalletSpendBundle(
            [*spends, make_spend(coin=fund_coin.coin, puzzle_reveal=ACS, solution=Program.to(conditions))],
            G2Element(),
        )
    )
    assert result == (MempoolInclusionStatus.SUCCESS, None)
    await sim.farm_block()

    # Test syncing from launcher
    assert (
        PlotNFT.get_next_from_coin_spend(coin_spend=spends[1], genesis_challenge=sim.defaults.GENESIS_CHALLENGE)
        == plotnft
    )
    return plotnft


# PlotNFT goes from self custody -> pooling -> waiting_room -> self custody
@pytest.mark.anyio
async def test_plotnft_transitions(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, sim_client):
        plotnft = await mint_plotnft(sim=sim, sim_client=sim_client, desired_state="self_custody")

        # Join a pool
        dpuz_hash, coin_spends = plotnft.join_pool(
            user_config=plotnft.user_config,
            pool_config=PoolConfig(pool_puzzle_hash=POOL_PUZZLE_HASH, timelock=uint64(1000)),
        )
        result = await sim_client.push_tx(
            cost_logger.add_cost(
                "Self Custody -> Pooling",
                WalletSpendBundle(
                    coin_spends,
                    user_sk.sign(dpuz_hash + plotnft.coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA),
                ),
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        plotnft = PlotNFT.get_next_from_coin_spend(
            coin_spend=coin_spends[0], genesis_challenge=sim.defaults.GENESIS_CHALLENGE
        )

        # Attempt to leave without waiting room
        quick_exit_dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=ACS, solution=Program.to([CreateCoin(bytes32.zeros, uint64(1)).to_program()])
        )
        singing_info = plotnft.modify_delegated_puzzle_and_solution(quick_exit_dpuz_and_solution)
        coin_spends = plotnft.exit_to_waiting_room(quick_exit_dpuz_and_solution)
        result = await sim_client.push_tx(
            WalletSpendBundle(
                coin_spends,
                user_sk.sign(
                    singing_info.puzzle.get_tree_hash() + plotnft.coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA
                ),
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # # Attempt to make a message while leaving
        waiting_room_custody = plotnft.waiting_room_puzzle()
        message_dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=ACS,
            solution=Program.to(
                [
                    CreateCoin(waiting_room_custody.inner_puzzle_hash(), uint64(1)).to_program(),
                    SendMessage(
                        bytes32.zeros,
                        sender=MessageParticipant(parent_id_committed=bytes32.zeros),
                        receiver=MessageParticipant(parent_id_committed=bytes32.zeros),
                    ).to_program(),
                ]
            ),
        )
        singing_info = plotnft.modify_delegated_puzzle_and_solution(message_dpuz_and_solution)
        coin_spends = plotnft.exit_to_waiting_room(message_dpuz_and_solution)
        result = await sim_client.push_tx(
            WalletSpendBundle(
                coin_spends,
                user_sk.sign(
                    singing_info.puzzle.get_tree_hash() + plotnft.coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA
                ),
            )
        )
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)

        # Leave honestly
        honest_exit_dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=ACS,
            solution=Program.to(
                [CreateCoin(puzzle_hash=waiting_room_custody.inner_puzzle_hash(), amount=uint64(1)).to_program()]
            ),
        )
        singing_info = plotnft.modify_delegated_puzzle_and_solution(honest_exit_dpuz_and_solution)
        coin_spends = plotnft.exit_to_waiting_room(honest_exit_dpuz_and_solution)
        result = await sim_client.push_tx(
            cost_logger.add_cost(
                "Pooling -> Waiting Room",
                WalletSpendBundle(
                    coin_spends,
                    user_sk.sign(
                        singing_info.puzzle.get_tree_hash()
                        + plotnft.coin.name()
                        + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA
                    ),
                ),
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        plotnft = PlotNFT.get_next_from_coin_spend(
            coin_spend=coin_spends[0],
            genesis_challenge=sim.defaults.GENESIS_CHALLENGE,
            previous_plotnft_puzzle=plotnft,
        )

        # Return to self-pooling
        self_custody_puzzle = replace(plotnft, pool_config=PoolConfig(), exiting=False)
        exit_dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=ACS,
            solution=Program.to(
                [
                    AssertSecondsRelative(seconds=plotnft.timelock).to_program(),
                    CreateCoin(puzzle_hash=self_custody_puzzle.inner_puzzle_hash(), amount=uint64(1)).to_program(),
                ]
            ),
        )
        singing_info = plotnft.modify_delegated_puzzle_and_solution(exit_dpuz_and_solution)
        coin_spends = plotnft.exit_waiting_room(exit_dpuz_and_solution)
        timelocked_spend = WalletSpendBundle(
            coin_spends,
            user_sk.sign(
                singing_info.puzzle.get_tree_hash() + plotnft.coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA
            ),
        )
        result = await sim_client.push_tx(timelocked_spend)
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_SECONDS_RELATIVE_FAILED)
        sim.pass_time(plotnft.timelock)
        await sim.farm_block()
        result = await sim_client.push_tx(cost_logger.add_cost("Waiting Room -> Self Custody", timelocked_spend))
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()

        # Check that it's there
        plotnft = PlotNFT.get_next_from_coin_spend(
            coin_spend=coin_spends[0],
            genesis_challenge=sim.defaults.GENESIS_CHALLENGE,
            previous_plotnft_puzzle=plotnft,
        )
        assert await sim_client.get_coin_record_by_name(plotnft.coin.name()) is not None


async def mint_reward(sim: SpendSim, sim_client: SimClient, singleton_id: bytes32) -> PoolReward:
    reward_puzzle = RewardPuzzle(singleton_id=singleton_id)
    await sim.farm_block(reward_puzzle.puzzle_hash())
    coin_1, coin_2 = await sim_client.get_coin_records_by_puzzle_hash(reward_puzzle.puzzle_hash())
    if coin_1.coin.amount > coin_2.coin.amount:
        return PoolReward(coin=coin_1.coin, height=sim.block_height, puzzle=reward_puzzle)
    else:
        return PoolReward(coin=coin_2.coin, height=sim.block_height, puzzle=reward_puzzle)


# PlotNFT claims pooling rewards while self custody
@pytest.mark.anyio
async def test_plotnft_self_custody_claim(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, sim_client):
        plotnft = await mint_plotnft(sim=sim, sim_client=sim_client, desired_state="self_custody")
        reward = await mint_reward(sim=sim, sim_client=sim_client, singleton_id=plotnft.singleton_struct.launcher_id)

        reward_dpuz_and_sol = DelegatedPuzzleAndSolution(
            puzzle=ACS, solution=Program.to([CreateCoin(bytes32.zeros, uint64(1)).to_program()])
        )
        signing_target, coin_spends = plotnft.claim_pool_reward(
            reward=reward, reward_delegated_puzzle_and_solution=reward_dpuz_and_sol
        )
        result = await sim_client.push_tx(
            cost_logger.add_cost(
                "Claim Pool Reward",
                WalletSpendBundle(
                    coin_spends,
                    user_sk.sign(signing_target + plotnft.coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA),
                ),
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()

        # Make sure the pooling reward did what it was supposed to
        assert len(await sim_client.get_coin_records_by_puzzle_hash(bytes32.zeros)) == 1

        # Make sure we can find the plotnft
        plotnft = PlotNFT.get_next_from_coin_spend(
            coin_spend=coin_spends[0],
            genesis_challenge=sim.defaults.GENESIS_CHALLENGE,
            previous_plotnft_puzzle=plotnft,
        )


# PlotNFT claims pooling rewards while pooling
@pytest.mark.parametrize("desired_state", ["waiting_room", "pooling"])
@pytest.mark.anyio
async def test_plotnft_pooling_claim(
    cost_logger: CostLogger, desired_state: Literal["waiting_room", "pooling"]
) -> None:
    async with sim_and_client() as (sim, sim_client):
        plotnft = await mint_plotnft(sim=sim, sim_client=sim_client, desired_state=desired_state)
        reward = await mint_reward(sim=sim, sim_client=sim_client, singleton_id=plotnft.singleton_struct.launcher_id)

        coin_spends = plotnft.forward_pool_reward(reward=reward)
        result = await sim_client.push_tx(
            cost_logger.add_cost(
                "Forward Pool Reward",
                WalletSpendBundle(
                    coin_spends,
                    G2Element(),
                ),
            )
        )
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()

        # Make sure the pooling reward did what it was supposed to
        assert len(await sim_client.get_coin_records_by_puzzle_hash(plotnft.pool_puzzle_hash)) == 1

        # Make sure we can find the plotnft
        plotnft = PlotNFT.get_next_from_coin_spend(
            coin_spend=coin_spends[0],
            genesis_challenge=sim.defaults.GENESIS_CHALLENGE,
            previous_plotnft_puzzle=plotnft,
        )
