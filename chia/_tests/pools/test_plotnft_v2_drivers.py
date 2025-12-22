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
    PlotNFTConfig,
    PoolingCustody,
    PoolReward,
    RewardPuzzle,
    SelfCustody,
)
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.wallet.conditions import AssertSecondsRelative, CreateCoin, MessageParticipant, SendMessage
from chia.wallet.puzzles.custody.custody_architecture import DelegatedPuzzleAndSolution
from chia.wallet.puzzles.custody.member_puzzles import BLSWithTaprootMember
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

    origin_coin, launcher_coin = PlotNFT.origin_coin_info([fund_coin.coin])

    if desired_state in {"pooling", "waiting_room"}:
        custody: PoolingCustody | SelfCustody = PoolingCustody(
            launcher_id=launcher_coin.name(),
            synthetic_pubkey=user_sk.get_g1(),
            pool_puzzle_hash=POOL_PUZZLE_HASH,
            timelock=uint64(1000),
            exiting=desired_state == "waiting_room",
            genesis_challenge=sim.defaults.GENESIS_CHALLENGE,
        )
    else:
        custody = SelfCustody(member=BLSWithTaprootMember(synthetic_key=user_sk.get_g1()))

    conditions, spends, plotnft = PlotNFT.launch(origin_coins=[origin_coin], custody=custody)

    result = await sim_client.push_tx(
        WalletSpendBundle(
            [*spends, make_spend(coin=origin_coin, puzzle_reveal=ACS, solution=Program.to(conditions))],
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
        custody = PoolingCustody(
            launcher_id=plotnft.puzzle.launcher_id,
            synthetic_pubkey=plotnft.puzzle.config.self_custody_pubkey,
            pool_puzzle_hash=POOL_PUZZLE_HASH,
            timelock=uint64(1000),
            exiting=False,
            genesis_challenge=sim.defaults.GENESIS_CHALLENGE,
        )
        dpuz_hash, coin_spends = plotnft.join_pool(custody)
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
        assert isinstance(plotnft.puzzle.inner_custody, PoolingCustody)
        quick_exit_dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=ACS, solution=Program.to([CreateCoin(bytes32.zeros, uint64(1)).to_program()])
        )
        singing_info = plotnft.puzzle.inner_custody.modify_delegated_puzzle_and_solution(quick_exit_dpuz_and_solution)
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
        waiting_room_custody = replace(custody, exiting=True)
        message_dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=ACS,
            solution=Program.to(
                [
                    CreateCoin(waiting_room_custody.puzzle_hash(nonce=0), uint64(1)).to_program(),
                    SendMessage(
                        bytes32.zeros,
                        sender=MessageParticipant(parent_id_committed=bytes32.zeros),
                        receiver=MessageParticipant(parent_id_committed=bytes32.zeros),
                    ).to_program(),
                ]
            ),
        )
        singing_info = plotnft.puzzle.inner_custody.modify_delegated_puzzle_and_solution(message_dpuz_and_solution)
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
                [CreateCoin(puzzle_hash=waiting_room_custody.puzzle_hash(nonce=0), amount=uint64(1)).to_program()]
            ),
        )
        singing_info = plotnft.puzzle.inner_custody.modify_delegated_puzzle_and_solution(honest_exit_dpuz_and_solution)
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
        assert plotnft.puzzle.inner_custody.self_custody.member.synthetic_key is not None
        plotnft = PlotNFT.get_next_from_coin_spend(
            coin_spend=coin_spends[0],
            genesis_challenge=sim.defaults.GENESIS_CHALLENGE,
            previous_pool_config=PlotNFTConfig(
                self_custody_pubkey=plotnft.puzzle.inner_custody.self_custody.member.synthetic_key,
                pool_puzzle_hash=plotnft.puzzle.inner_custody.pool_puzzle_hash,
                timelock=plotnft.puzzle.inner_custody.timelock,
            ),
        )

        # Return to self-pooling
        assert isinstance(plotnft.puzzle.inner_custody, PoolingCustody)
        exit_dpuz_and_solution = DelegatedPuzzleAndSolution(
            puzzle=ACS,
            solution=Program.to(
                [
                    AssertSecondsRelative(seconds=plotnft.puzzle.inner_custody.timelock).to_program(),
                    CreateCoin(
                        puzzle_hash=plotnft.puzzle.inner_custody.self_custody.puzzle_hash(nonce=0), amount=uint64(1)
                    ).to_program(),
                ]
            ),
        )
        singing_info = plotnft.puzzle.inner_custody.modify_delegated_puzzle_and_solution(exit_dpuz_and_solution)
        coin_spends = plotnft.exit_waiting_room(exit_dpuz_and_solution)
        timelocked_spend = WalletSpendBundle(
            coin_spends,
            user_sk.sign(
                singing_info.puzzle.get_tree_hash() + plotnft.coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA
            ),
        )
        result = await sim_client.push_tx(timelocked_spend)
        assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_SECONDS_RELATIVE_FAILED)
        sim.pass_time(plotnft.puzzle.inner_custody.timelock)
        await sim.farm_block()
        result = await sim_client.push_tx(cost_logger.add_cost("Waiting Room -> Self Custody", timelocked_spend))
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()

        # Check that it's there
        plotnft = PlotNFT.get_next_from_coin_spend(
            coin_spend=coin_spends[0],
            genesis_challenge=sim.defaults.GENESIS_CHALLENGE,
            previous_pool_config=plotnft.puzzle.config,
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
        reward = await mint_reward(
            sim=sim, sim_client=sim_client, singleton_id=plotnft.puzzle.singleton_struct.launcher_id
        )

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
            previous_pool_config=plotnft.puzzle.config,
        )


# PlotNFT claims pooling rewards while pooling
@pytest.mark.parametrize("desired_state", ["waiting_room", "pooling"])
@pytest.mark.anyio
async def test_plotnft_pooling_claim(
    cost_logger: CostLogger, desired_state: Literal["waiting_room", "pooling"]
) -> None:
    async with sim_and_client() as (sim, sim_client):
        plotnft = await mint_plotnft(sim=sim, sim_client=sim_client, desired_state=desired_state)
        reward = await mint_reward(
            sim=sim, sim_client=sim_client, singleton_id=plotnft.puzzle.singleton_struct.launcher_id
        )

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
        assert isinstance(plotnft.puzzle.inner_custody, PoolingCustody)
        assert len(await sim_client.get_coin_records_by_puzzle_hash(plotnft.puzzle.inner_custody.pool_puzzle_hash)) == 1

        # Make sure we can find the plotnft
        assert plotnft.puzzle.inner_custody.self_custody.member.synthetic_key is not None
        plotnft = PlotNFT.get_next_from_coin_spend(
            coin_spend=coin_spends[0],
            genesis_challenge=sim.defaults.GENESIS_CHALLENGE,
            previous_pool_config=PlotNFTConfig(
                self_custody_pubkey=plotnft.puzzle.inner_custody.self_custody.member.synthetic_key,
                pool_puzzle_hash=plotnft.puzzle.inner_custody.pool_puzzle_hash,
                timelock=plotnft.puzzle.inner_custody.timelock,
            ),
        )
