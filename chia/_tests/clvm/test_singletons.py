from __future__ import annotations

from typing import List, Optional, Tuple

import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia._tests.clvm.test_puzzles import public_key_for_index, secret_exponent_for_index
from chia._tests.util.key_tool import KeyTool
from chia.clvm.spend_sim import CostLogger, SimClient, SpendSim, sim_and_client
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.util.ints import uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles import p2_conditions, p2_delegated_puzzle_or_hidden_puzzle

"""
This test suite aims to test:
    - chia.wallet.puzzles.singleton_top_layer.py
    - chia.wallet.puzzles.singleton_top_layer.clsp
    - chia.wallet.puzzles.singleton_top_layer_v1_1.py
    - chia.wallet.puzzles.singleton_top_layer_v1_1.clsp
    - chia.wallet.puzzles.p2_singleton.clsp
    - chia.wallet.puzzles.p2_singleton_or_delayed_puzhash.clsp
"""


class TransactionPushError(Exception):
    pass


def sign_delegated_puz(del_puz: Program, coin: Coin) -> G2Element:
    synthetic_secret_key: PrivateKey = p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_secret_key(  # noqa
        PrivateKey.from_bytes(
            secret_exponent_for_index(1).to_bytes(32, "big"),
        ),
        p2_delegated_puzzle_or_hidden_puzzle.DEFAULT_HIDDEN_PUZZLE_HASH,
    )
    return AugSchemeMPL.sign(
        synthetic_secret_key,
        (del_puz.get_tree_hash() + coin.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA),  # noqa
    )


# Helper function
async def make_and_spend_bundle(
    sim: SpendSim,
    sim_client: SimClient,
    coin: Coin,
    delegated_puzzle: Program,
    coinsols: List[CoinSpend],
    ex_error: Optional[Err] = None,
    fail_msg: str = "",
    cost_logger: Optional[CostLogger] = None,
    cost_log_msg: str = "",
):
    signature: G2Element = sign_delegated_puz(delegated_puzzle, coin)
    spend_bundle = SpendBundle(
        coinsols,
        signature,
    )
    if cost_logger is not None:
        spend_bundle = cost_logger.add_cost(cost_log_msg, spend_bundle)

    try:
        result, error = await sim_client.push_tx(spend_bundle)
        if error is None:
            await sim.farm_block()
        elif ex_error is not None:
            assert error == ex_error
        else:
            raise TransactionPushError(error)
    except AssertionError:
        raise AssertionError(fail_msg)


@pytest.mark.anyio
@pytest.mark.parametrize("version", [0, 1])
async def test_singleton_top_layer(version, cost_logger):
    async with sim_and_client() as (sim, sim_client):
        # START TESTS
        # Generate starting info
        key_lookup = KeyTool()
        pk: G1Element = G1Element.from_bytes(public_key_for_index(1, key_lookup))
        starting_puzzle: Program = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_pk(pk)  # noqa

        if version == 0:
            from chia.wallet.puzzles import singleton_top_layer

            adapted_puzzle: Program = singleton_top_layer.adapt_inner_to_singleton(starting_puzzle)  # noqa
        else:
            from chia.wallet.puzzles import singleton_top_layer_v1_1 as singleton_top_layer

            adapted_puzzle = starting_puzzle
        adapted_puzzle_hash: bytes32 = adapted_puzzle.get_tree_hash()

        # Get our starting standard coin created
        START_AMOUNT: uint64 = 1023
        await sim.farm_block(starting_puzzle.get_tree_hash())
        starting_coin: Coin = await sim_client.get_coin_records_by_puzzle_hash(starting_puzzle.get_tree_hash())
        starting_coin = starting_coin[0].coin
        comment: List[Tuple[str, str]] = [("hello", "world")]

        # LAUNCHING
        # Try to create an even singleton (driver test)
        try:
            conditions, launcher_coinsol = singleton_top_layer.launch_conditions_and_coinsol(  # noqa
                starting_coin, adapted_puzzle, comment, (START_AMOUNT - 1)
            )
            raise AssertionError("This should fail due to an even amount")
        except ValueError as msg:
            assert str(msg) == "Coin amount cannot be even. Subtract one mojo."
            conditions, launcher_coinsol = singleton_top_layer.launch_conditions_and_coinsol(  # noqa
                starting_coin, adapted_puzzle, comment, START_AMOUNT
            )

        # Creating solution for standard transaction
        delegated_puzzle: Program = p2_conditions.puzzle_for_conditions(conditions)  # noqa
        full_solution: Program = p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(conditions)  # noqa

        starting_coinsol = make_spend(
            starting_coin,
            starting_puzzle,
            full_solution,
        )

        await make_and_spend_bundle(
            sim,
            sim_client,
            starting_coin,
            delegated_puzzle,
            [starting_coinsol, launcher_coinsol],
            cost_logger=cost_logger,
            cost_log_msg="Singleton Launch + Standard TX",
        )

        # EVE
        singleton_eve: Coin = (await sim.all_non_reward_coins())[0]
        launcher_coin: Coin = singleton_top_layer.generate_launcher_coin(
            starting_coin,
            START_AMOUNT,
        )
        launcher_id: bytes32 = launcher_coin.name()
        # This delegated puzzle just recreates the coin exactly
        delegated_puzzle: Program = Program.to(
            (
                1,
                [
                    [
                        ConditionOpcode.CREATE_COIN,
                        adapted_puzzle_hash,
                        singleton_eve.amount,
                    ]
                ],
            )
        )
        inner_solution: Program = Program.to([[], delegated_puzzle, []])
        # Generate the lineage proof we will need from the launcher coin
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(launcher_coinsol)  # noqa
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof,
            singleton_eve.amount,
            inner_solution,
        )

        singleton_eve_coinsol = make_spend(
            singleton_eve,
            puzzle_reveal,
            full_solution,
        )

        await make_and_spend_bundle(
            sim,
            sim_client,
            singleton_eve,
            delegated_puzzle,
            [singleton_eve_coinsol],
            cost_logger=cost_logger,
            cost_log_msg="Singleton Eve Spend w/ Standard TX",
        )

        # POST-EVE
        singleton: Coin = (await sim.all_non_reward_coins())[0]
        # Same delegated_puzzle / inner_solution. We're just recreating ourself
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(singleton_eve_coinsol)  # noqa
        # Same puzzle_reveal too
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof,
            singleton.amount,
            inner_solution,
        )

        singleton_coinsol = make_spend(
            singleton,
            puzzle_reveal,
            full_solution,
        )

        await make_and_spend_bundle(
            sim,
            sim_client,
            singleton,
            delegated_puzzle,
            [singleton_coinsol],
            cost_logger=cost_logger,
            cost_log_msg="Singleton Spend + Standard TX",
        )

        # CLAIM A P2_SINGLETON
        singleton_child: Coin = (await sim.all_non_reward_coins())[0]
        p2_singleton_puz: Program = singleton_top_layer.pay_to_singleton_puzzle(launcher_id)
        p2_singleton_ph: bytes32 = p2_singleton_puz.get_tree_hash()
        await sim.farm_block(p2_singleton_ph)
        p2_singleton_coin: Coin = await sim_client.get_coin_records_by_puzzle_hash(p2_singleton_ph)
        p2_singleton_coin = p2_singleton_coin[0].coin
        assertion, announcement, claim_coinsol = singleton_top_layer.claim_p2_singleton(
            p2_singleton_coin,
            adapted_puzzle_hash,
            launcher_id,
        )
        delegated_puzzle: Program = Program.to(
            (
                1,
                [
                    [ConditionOpcode.CREATE_COIN, adapted_puzzle_hash, singleton_eve.amount],
                    assertion,
                    announcement,
                ],
            )
        )
        inner_solution: Program = Program.to([[], delegated_puzzle, []])
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(singleton_coinsol)
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof,
            singleton_eve.amount,
            inner_solution,
        )
        singleton_claim_coinsol = make_spend(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        await make_and_spend_bundle(
            sim,
            sim_client,
            singleton_child,
            delegated_puzzle,
            [singleton_claim_coinsol, claim_coinsol],
            cost_logger=cost_logger,
            cost_log_msg="Singleton w/ Standard TX claim p2_singleton",
        )

        # CLAIM A P2_SINGLETON_OR_DELAYED
        singleton_child: Coin = (await sim.all_non_reward_coins())[0]
        DELAY_TIME: uint64 = 1
        DELAY_PH: bytes32 = adapted_puzzle_hash
        p2_singleton_puz: Program = singleton_top_layer.pay_to_singleton_or_delay_puzzle(
            launcher_id,
            DELAY_TIME,
            DELAY_PH,
        )
        p2_singleton_ph: bytes32 = p2_singleton_puz.get_tree_hash()
        ARBITRARY_AMOUNT: uint64 = 250000000000
        await sim.farm_block(p2_singleton_ph)
        p2_singleton_coin: Coin = await sim_client.get_coin_records_by_puzzle_hash(p2_singleton_ph)
        p2_singleton_coin = sorted(p2_singleton_coin, key=lambda x: x.coin.amount)[0].coin
        assertion, announcement, claim_coinsol = singleton_top_layer.claim_p2_singleton(
            p2_singleton_coin,
            adapted_puzzle_hash,
            launcher_id,
            DELAY_TIME,
            DELAY_PH,
        )
        delegated_puzzle: Program = Program.to(
            (
                1,
                [
                    [ConditionOpcode.CREATE_COIN, adapted_puzzle_hash, singleton_eve.amount],
                    assertion,
                    announcement,
                ],
            )
        )
        inner_solution: Program = Program.to([[], delegated_puzzle, []])
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(singleton_claim_coinsol)
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof,
            singleton_eve.amount,
            inner_solution,
        )
        delay_claim_coinsol = make_spend(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        # Save the height so we can rewind after this
        save_height: uint64 = sim.get_height()  # The last coin solution before this point is singleton_claim_coinsol
        await make_and_spend_bundle(
            sim,
            sim_client,
            singleton_child,
            delegated_puzzle,
            [delay_claim_coinsol, claim_coinsol],
            cost_logger=cost_logger,
            cost_log_msg="Singleton w/ Standard TX claim p2_singleton_or_delayed",
        )

        # TRY TO SPEND AWAY TOO SOON (Negative Test)
        await sim.rewind(save_height)
        to_delay_ph_coinsol: CoinSpend = singleton_top_layer.spend_to_delayed_puzzle(
            p2_singleton_coin,
            ARBITRARY_AMOUNT,
            launcher_id,
            DELAY_TIME,
            DELAY_PH,
        )
        result, error = await sim_client.push_tx(SpendBundle([to_delay_ph_coinsol], G2Element()))
        assert error == Err.ASSERT_SECONDS_RELATIVE_FAILED

        # SPEND TO DELAYED PUZZLE HASH
        await sim.rewind(save_height)
        sim.pass_time(10000005)
        sim.pass_blocks(100)
        await sim_client.push_tx(SpendBundle([to_delay_ph_coinsol], G2Element()))

        # CREATE MULTIPLE ODD CHILDREN (Negative Test)
        singleton_child: Coin = (await sim.all_non_reward_coins())[0]
        delegated_puzzle: Program = Program.to(
            (
                1,
                [
                    [ConditionOpcode.CREATE_COIN, adapted_puzzle_hash, 3],
                    [ConditionOpcode.CREATE_COIN, adapted_puzzle_hash, 7],
                ],
            )
        )
        inner_solution: Program = Program.to([[], delegated_puzzle, []])
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(singleton_claim_coinsol)
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_child.amount, inner_solution
        )

        multi_odd_coinsol = make_spend(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        await make_and_spend_bundle(
            sim,
            sim_client,
            singleton_child,
            delegated_puzzle,
            [multi_odd_coinsol],
            ex_error=Err.GENERATOR_RUNTIME_ERROR,
            fail_msg="Too many odd children were allowed",
        )

        # CREATE NO ODD CHILDREN (Negative Test)
        delegated_puzzle: Program = Program.to(
            (
                1,
                [
                    [ConditionOpcode.CREATE_COIN, adapted_puzzle_hash, 4],
                    [ConditionOpcode.CREATE_COIN, adapted_puzzle_hash, 10],
                ],
            )
        )
        inner_solution: Program = Program.to([[], delegated_puzzle, []])
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(singleton_claim_coinsol)
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_child.amount, inner_solution
        )

        no_odd_coinsol = make_spend(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        await make_and_spend_bundle(
            sim,
            sim_client,
            singleton_child,
            delegated_puzzle,
            [no_odd_coinsol],
            ex_error=Err.GENERATOR_RUNTIME_ERROR,
            fail_msg="Need at least one odd child",
        )

        # ATTEMPT TO CREATE AN EVEN SINGLETON (Negative test)
        await sim.rewind(save_height)

        delegated_puzzle: Program = Program.to(
            (
                1,
                [
                    [
                        ConditionOpcode.CREATE_COIN,
                        singleton_child.puzzle_hash,
                        2,
                    ],
                    [ConditionOpcode.CREATE_COIN, adapted_puzzle_hash, 1],
                ],
            )
        )
        inner_solution: Program = Program.to([[], delegated_puzzle, []])
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(singleton_claim_coinsol)
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_child.amount, inner_solution
        )

        singleton_even_coinsol = make_spend(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        await make_and_spend_bundle(
            sim,
            sim_client,
            singleton_child,
            delegated_puzzle,
            [singleton_even_coinsol],
        )

        # Now try a perfectly innocent spend
        evil_coin: Coin = next(filter(lambda c: c.amount == 2, (await sim.all_non_reward_coins())))
        delegated_puzzle: Program = Program.to(
            (
                1,
                [
                    [
                        ConditionOpcode.CREATE_COIN,
                        adapted_puzzle_hash,
                        1,
                    ],
                ],
            )
        )
        inner_solution: Program = Program.to([[], delegated_puzzle, []])
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(singleton_even_coinsol)  # noqa
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof,
            1,
            inner_solution,
        )

        evil_coinsol = make_spend(
            evil_coin,
            puzzle_reveal,
            full_solution,
        )

        await make_and_spend_bundle(
            sim,
            sim_client,
            evil_coin,
            delegated_puzzle,
            [evil_coinsol],
            ex_error=Err.ASSERT_MY_COIN_ID_FAILED if version == 0 else Err.ASSERT_MY_AMOUNT_FAILED,
            fail_msg="This coin is even!",
        )

        # MELTING
        # Remember, we're still spending singleton_child
        await sim.rewind(save_height)
        conditions = [
            singleton_top_layer.MELT_CONDITION,
            [
                ConditionOpcode.CREATE_COIN,
                adapted_puzzle_hash,
                (singleton_child.amount - 1),
            ],
        ]
        delegated_puzzle: Program = p2_conditions.puzzle_for_conditions(conditions)
        inner_solution: Program = p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(conditions)
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(singleton_claim_coinsol)
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_child.amount, inner_solution
        )

        melt_coinsol = make_spend(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        await make_and_spend_bundle(
            sim,
            sim_client,
            singleton_child,
            delegated_puzzle,
            [melt_coinsol],
            cost_logger=cost_logger,
            cost_log_msg="Singleton w/ Standard TX melt",
        )

        melted_coin: Coin = (await sim.all_non_reward_coins())[0]
        assert melted_coin.puzzle_hash == adapted_puzzle_hash
