from __future__ import annotations

from typing import List, Optional

import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia._tests.clvm.benchmark_costs import cost_of_spend_bundle
from chia._tests.clvm.test_puzzles import (
    public_key_for_index,
    secret_exponent_for_index,
)
from chia._tests.util.key_tool import KeyTool
from chia._tests.util.spend_sim import CostLogger, SimClient, SpendSim, sim_and_client
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles import (
    p2_conditions,
    p2_delegated_puzzle_or_hidden_puzzle,
    singleton_top_layer_v1_1 as singleton_top_layer,
)
from chia.wallet.revocable_cats.revocable_cats_driver import (
    construct_revocable_cat_inner_puzzle,
    construct_revocation_layer,
    construct_everything_with_singleton_cat_tail,
    construct_p2_delegated_by_singleton,
    solve_p2_delegated_by_singleton,
    solve_revocation_layer,
)
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


"""
This test suite aims to test:
    - chia.wallet.revocable_cats.revocable_cats_driver.py
    - chia.wallet.revocable_cats.revocation_layer.clsp
    - chia.wallet.revocable_cats.everything_with_singleton.clsp
    - chia.wallet.revocable_cats.p2_delegated_by_singleton.clsp
"""


class TransactionPushError(Exception):
    pass


def sign_delegated_puz(del_puz: Program, coin: Coin, index: int = 1) -> G2Element:
    synthetic_secret_key: PrivateKey = (
        p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_secret_key(
            PrivateKey.from_bytes(
                secret_exponent_for_index(index).to_bytes(32, "big"),
            ),
            p2_delegated_puzzle_or_hidden_puzzle.DEFAULT_HIDDEN_PUZZLE_HASH,
        )
    )
    return AugSchemeMPL.sign(
        synthetic_secret_key,
        (
            del_puz.get_tree_hash()
            + coin.name()
            + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
        ),
    )


async def spend_cat(
    sim: SpendSim,
    sim_client: SimClient,
    tail: Program,
    coins: list[Coin],
    lineage_proofs: list[LineageProof],
    inner_solutions: list[Program],
    p2_puzzle: Program,
    expected_result: tuple[MempoolInclusionStatus, Optional[Err]],
    reveal_limitations_program: bool = True,
    signatures: list[G2Element] = [],
    extra_deltas: Optional[list[int]] = None,
    additional_spends: list[WalletSpendBundle] = [],
    limitations_solutions: Optional[list[Program]] = None,
    cost_logger: Optional[CostLogger] = None,
    cost_log_msg: str = "",
) -> int:
    if limitations_solutions is None:
        limitations_solutions = [Program.to([])] * len(coins)
    if extra_deltas is None:
        extra_deltas = [0] * len(coins)

    spendable_cat_list: list[SpendableCAT] = []
    for coin, innersol, proof, limitations_solution, extra_delta in zip(
        coins, inner_solutions, lineage_proofs, limitations_solutions, extra_deltas
    ):
        spendable_cat_list.append(
            SpendableCAT(
                coin,
                tail.get_tree_hash(),
                p2_puzzle,
                innersol,
                limitations_solution=limitations_solution,
                lineage_proof=proof,
                extra_delta=extra_delta,
                limitations_program_reveal=(
                    tail if reveal_limitations_program else Program.to([])
                ),
            )
        )

    spend_bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, spendable_cat_list)
    agg_sig = AugSchemeMPL.aggregate(signatures)
    final_bundle = WalletSpendBundle.aggregate(
        [
            *additional_spends,
            spend_bundle,
            WalletSpendBundle([], agg_sig),
        ]  # "Signing" the spend bundle
    )
    for spend in spend_bundle.coin_spends:
        print(spend.coin.name().hex())
    if cost_logger is not None:
        final_bundle = cost_logger.add_cost(cost_log_msg, final_bundle)

    result = await sim_client.push_tx(final_bundle)
    assert result == expected_result
    cost = cost_of_spend_bundle(spend_bundle)
    await sim.farm_block()
    return cost


# Helper function
async def make_and_spend_bundle(
    sim: SpendSim,
    sim_client: SimClient,
    coin: Coin,
    delegated_puzzle: Program,
    coinsols: list[CoinSpend],
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
        for spend in spend_bundle.coin_spends:
            print(f"SPEND: {spend.coin.name().hex()}")
        _result, error = await sim_client.push_tx(spend_bundle)
        if error is None:
            await sim.farm_block()
        elif ex_error is not None:
            assert error == ex_error
        else:
            raise TransactionPushError(error)
    except AssertionError:
        raise AssertionError(fail_msg)


@pytest.mark.anyio
async def test_revocable_cat_lifecycle(cost_logger):
    async with sim_and_client() as (sim, sim_client):
        # START TESTS
        # Generate starting info
        key_lookup = KeyTool()
        pk: G1Element = G1Element.from_bytes(public_key_for_index(1, key_lookup))
        singleton_p2_puzzle: Program = (
            p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_pk(pk)
        )

        singleton_p2_puzzle_hash: bytes32 = singleton_p2_puzzle.get_tree_hash()

        # Get our starting standard coin created
        START_AMOUNT: uint64 = uint64(1)
        await sim.farm_block(singleton_p2_puzzle.get_tree_hash())
        starting_coin_list: List[CoinRecord] = (
            await sim_client.get_coin_records_by_puzzle_hash(
                singleton_p2_puzzle.get_tree_hash()
            )
        )
        starting_coin = starting_coin_list[0].coin
        comment: list[tuple[str, str]] = [("hello", "world")]

        # Singleton Launch
        conditions, launcher_coinsol = (
            singleton_top_layer.launch_conditions_and_coinsol(
                starting_coin, singleton_p2_puzzle, comment, START_AMOUNT
            )
        )

        # Creating solution for standard transaction
        delegated_puzzle: Program = p2_conditions.puzzle_for_conditions(conditions)
        inner_solution: Program = (
            p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(conditions)
        )

        starting_coinsol = make_spend(
            starting_coin,
            singleton_p2_puzzle,
            inner_solution,
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

        # Singleton Eve Spend
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
                        singleton_p2_puzzle_hash,
                        singleton_eve.amount,
                    ]
                ],
            )
        )
        inner_solution: Program = Program.to([[], delegated_puzzle, []])
        # Generate the lineage proof we will need from the launcher coin
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(
            launcher_coinsol
        )
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            singleton_p2_puzzle,
        )
        inner_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof,
            singleton_eve.amount,
            inner_solution,
        )

        singleton_eve_coinsol = make_spend(
            singleton_eve,
            puzzle_reveal,
            inner_solution,
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

        # Mint the CAT + authorize the mint via singleton

        user_pk: G1Element = G1Element.from_bytes(public_key_for_index(2, key_lookup))
        user_p2_puzzle: Program = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_pk(
            user_pk
        )

        user_p2_puzzle_hash: bytes32 = user_p2_puzzle.get_tree_hash()

        starting_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(
                singleton_p2_puzzle_hash, include_spent_coins=False
            )
        )[0].coin

        hidden_puzzle_hash = Program.to(1).get_tree_hash()
        inner_puzzle_hash = Program.to(1).get_tree_hash()
        cat_inner_puzzle = construct_revocation_layer(
            hidden_puzzle_hash, inner_puzzle_hash
        )

        nonce = 0
        tail = construct_everything_with_singleton_cat_tail(launcher_id, nonce)
        tail_solution = Program.to([singleton_p2_puzzle_hash])
        cat_inner_puzzle = construct_revocable_cat_inner_puzzle(
            launcher_id, singleton_p2_puzzle_hash
        )
        cat_puzzle = construct_cat_puzzle(
            CAT_MOD, tail.get_tree_hash(), cat_inner_puzzle
        )
        cat_ph = cat_puzzle.get_tree_hash()

        conditions = [Program.to([51, cat_ph, starting_coin.amount])]
        delegated_puzzle: Program = p2_conditions.puzzle_for_conditions(conditions)
        inner_solution: Program = (
            p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(conditions)
        )
        cat_launch_spend = make_spend(
            starting_coin, singleton_p2_puzzle, inner_solution
        )
        cat_launch_signature: G2Element = sign_delegated_puz(
            delegated_puzzle, starting_coin
        )
        cat_launch_spend_bundle = WalletSpendBundle(
            [cat_launch_spend], cat_launch_signature
        )

        eve_coin = Coin(starting_coin.name(), cat_ph, starting_coin.amount)
        eve_conditions: List[Program] = [
            Program.to([51, user_p2_puzzle_hash, eve_coin.amount]),
            Program.to([51, 0, -113, tail, tail_solution]),
        ]
        delegated_puzzle: Program = p2_conditions.puzzle_for_conditions(eve_conditions)
        inner_solution: Program = (
            p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(eve_conditions)
        )
        cat_inner_solution = solve_revocation_layer(
            singleton_p2_puzzle, inner_solution, hidden=False
        )
        cat_eve_signature = sign_delegated_puz(delegated_puzzle, eve_coin)

        delegated_puzzle: Program = Program.to(
            (
                1,
                [
                    [
                        ConditionOpcode.CREATE_COIN,
                        singleton_p2_puzzle_hash,  # Recreate
                        singleton_eve.amount,
                    ],
                    [
                        ConditionOpcode.SEND_MESSAGE,
                        23,  # 010111 (puzzle to coin_id)
                        0,  # delta
                        eve_coin.name(),
                    ],
                ],
            )
        )
        inner_solution: Program = Program.to([[], delegated_puzzle, []])

        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            singleton_p2_puzzle,
        )

        singleton_post_eve: Coin = Coin(
            singleton_eve.name(),
            puzzle_reveal.get_tree_hash(),
            singleton_eve.amount,
        )

        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(
            singleton_eve_coinsol
        )
        inner_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof,
            singleton_eve.amount,
            inner_solution,
        )
        singleton_authorize_mint_coinsol = make_spend(
            singleton_post_eve,
            puzzle_reveal,
            inner_solution,
        )
        signature: G2Element = sign_delegated_puz(delegated_puzzle, singleton_post_eve)
        singleton_spend_bundle = WalletSpendBundle(
            [singleton_authorize_mint_coinsol], signature
        )

        await spend_cat(
            sim,
            sim_client,
            tail,
            [eve_coin],
            [LineageProof()],
            [cat_inner_solution],
            cat_inner_puzzle,
            (MempoolInclusionStatus.SUCCESS, None),
            signatures=[cat_eve_signature],
            additional_spends=[
                cat_launch_spend_bundle,
                singleton_spend_bundle,
            ],
            limitations_solutions=[tail_solution],
            cost_logger=cost_logger,
            cost_log_msg="Cat launch + eve spend - create one child (TAIL: everything_with_singleton)",
        )

        # Spend as user
        user_cat_inner_puzzle = construct_revocable_cat_inner_puzzle(
            launcher_id, user_p2_puzzle_hash
        )
        user_cat_puzzle = construct_cat_puzzle(
            CAT_MOD, tail.get_tree_hash(), user_cat_inner_puzzle
        )
        user_cat_ph = user_cat_puzzle.get_tree_hash()

        first_user_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(
                user_cat_ph, include_spent_coins=False
            )
        )[0].coin

        parent_coin = eve_coin
        lineage_proof = LineageProof(
            parent_coin.parent_coin_info,
            cat_inner_puzzle.get_tree_hash(),
            uint64(parent_coin.amount),
        )

        user_spend_conditions: List[Program] = [
            Program.to([51, user_p2_puzzle_hash, eve_coin.amount])
        ]
        delegated_puzzle: Program = p2_conditions.puzzle_for_conditions(
            user_spend_conditions
        )
        inner_solution: Program = (
            p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(
                user_spend_conditions
            )
        )
        user_spend_inner_solution = solve_revocation_layer(
            user_p2_puzzle, inner_solution, hidden=False
        )
        user_spend_signature = sign_delegated_puz(
            delegated_puzzle, first_user_coin, index=2
        )

        await spend_cat(
            sim,
            sim_client,
            tail,
            [first_user_coin],
            [lineage_proof],
            [user_spend_inner_solution],
            user_cat_inner_puzzle,
            (MempoolInclusionStatus.SUCCESS, None),
            signatures=[user_spend_signature],
            reveal_limitations_program=False,
            cost_logger=cost_logger,
            cost_log_msg="Cat spend by user",
        )

        # Revoke by singleton
        latest_user_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(
                user_cat_ph, include_spent_coins=False
            )
        )[0].coin

        parent_coin = first_user_coin
        cat_lineage_proof = LineageProof(
            parent_coin.parent_coin_info,
            user_cat_inner_puzzle.get_tree_hash(),
            uint64(parent_coin.amount),
        )

        singleton_inner_puzzle_hash = singleton_p2_puzzle.get_tree_hash()
        revoke_conditions = [
            Program.to([51, cat_inner_puzzle.get_tree_hash(), first_user_coin.amount]),
        ]
        revoke_delegated_puzzle: Program = p2_conditions.puzzle_for_conditions(
            revoke_conditions
        )
        revoke_inner_solution: Program = (
            p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(
                revoke_conditions
            )
        )
        hidden_puzzle = construct_p2_delegated_by_singleton(launcher_id)
        hidden_solution = solve_p2_delegated_by_singleton(
            singleton_inner_puzzle_hash,
            revoke_delegated_puzzle,
            revoke_inner_solution,
        )
        revoke_spend_inner_solution = solve_revocation_layer(
            hidden_puzzle, hidden_solution, hidden=True
        )

        singleton_delegated_puzzle: Program = Program.to(
            (
                1,
                [
                    [
                        ConditionOpcode.CREATE_COIN,
                        singleton_p2_puzzle_hash,  # Recreate
                        singleton_eve.amount,
                    ],
                    [
                        ConditionOpcode.SEND_MESSAGE,
                        23,  # 010111 (puzzle to coin_id)
                        revoke_delegated_puzzle.get_tree_hash(),
                        latest_user_coin.name(),
                    ],
                ],
            )
        )
        singleton_inner_solution: Program = Program.to(
            [[], singleton_delegated_puzzle, []]
        )

        singleton_puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            singleton_p2_puzzle,
        )

        singleton_latest_coin: Coin = Coin(
            singleton_post_eve.name(),
            singleton_puzzle_reveal.get_tree_hash(),
            singleton_post_eve.amount,
        )

        singleton_lineage_proof: LineageProof = (
            singleton_top_layer.lineage_proof_for_coinsol(
                singleton_authorize_mint_coinsol
            )
        )
        singleton_outer_solution: Program = singleton_top_layer.solution_for_singleton(
            singleton_lineage_proof,
            singleton_post_eve.amount,
            singleton_inner_solution,
        )
        singleton_revoke_coinsol = make_spend(
            singleton_latest_coin,
            singleton_puzzle_reveal,
            singleton_outer_solution,
        )
        singleton_signature: G2Element = sign_delegated_puz(
            singleton_delegated_puzzle, singleton_latest_coin
        )
        singleton_spend_bundle = WalletSpendBundle(
            [singleton_revoke_coinsol], singleton_signature
        )

        await spend_cat(
            sim,
            sim_client,
            tail,
            [latest_user_coin],
            [cat_lineage_proof],
            [revoke_spend_inner_solution],
            user_cat_inner_puzzle,
            (MempoolInclusionStatus.SUCCESS, None),
            additional_spends=[
                singleton_spend_bundle,
            ],
            limitations_solutions=[tail_solution],
            cost_logger=cost_logger,
            cost_log_msg="Cat revoke by singleton",
        )

        # Melt by singleton

        cat_coin_to_melt = (
            await sim_client.get_coin_records_by_puzzle_hash(
                cat_ph, include_spent_coins=False
            )
        )[0].coin

        parent_coin = latest_user_coin
        cat_lineage_proof = LineageProof(
            parent_coin.parent_coin_info,
            cat_inner_puzzle.get_tree_hash(),
            uint64(parent_coin.amount),
        )

        cat_melt_conditions = [
            Program.to([51, 0, -113, tail, tail_solution]),
        ]
        cat_delegated_puzzle: Program = p2_conditions.puzzle_for_conditions(
            cat_melt_conditions
        )
        cat_inner_solution: Program = (
            p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(
                cat_melt_conditions
            )
        )
        cat_revocation_layer_solution = solve_revocation_layer(
            singleton_p2_puzzle, cat_inner_solution, hidden=False
        )
        cat_melt_signature = sign_delegated_puz(cat_delegated_puzzle, cat_coin_to_melt)

        singleton_delegated_puzzle: Program = Program.to(
            (
                1,
                [
                    [
                        ConditionOpcode.CREATE_COIN,
                        singleton_p2_puzzle_hash,  # Recreate
                        singleton_eve.amount,
                    ],
                    [
                        ConditionOpcode.SEND_MESSAGE,
                        23,  # 010111 (puzzle to coin_id)
                        -cat_coin_to_melt.amount,  # delta
                        cat_coin_to_melt.name(),
                    ],
                ],
            )
        )
        singleton_inner_solution: Program = Program.to(
            [[], singleton_delegated_puzzle, []]
        )

        singleton_puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            singleton_p2_puzzle,
        )

        singleton_latest_coin: Coin = Coin(
            singleton_latest_coin.name(),
            singleton_puzzle_reveal.get_tree_hash(),
            singleton_latest_coin.amount,
        )

        singleton_lineage_proof: LineageProof = (
            singleton_top_layer.lineage_proof_for_coinsol(singleton_revoke_coinsol)
        )
        singleton_outer_solution: Program = singleton_top_layer.solution_for_singleton(
            singleton_lineage_proof,
            singleton_eve.amount,
            singleton_inner_solution,
        )
        singleton_melt_coinsol = make_spend(
            singleton_latest_coin,
            singleton_puzzle_reveal,
            singleton_outer_solution,
        )
        singleton_signature: G2Element = sign_delegated_puz(
            singleton_delegated_puzzle, singleton_latest_coin
        )
        singleton_spend_bundle = WalletSpendBundle(
            [singleton_melt_coinsol], singleton_signature
        )

        await spend_cat(
            sim,
            sim_client,
            tail,
            [cat_coin_to_melt],
            [cat_lineage_proof],
            [cat_revocation_layer_solution],
            cat_inner_puzzle,
            (MempoolInclusionStatus.SUCCESS, None),
            signatures=[cat_melt_signature],
            additional_spends=[
                singleton_spend_bundle,
            ],
            limitations_solutions=[tail_solution],
            extra_deltas=[-cat_coin_to_melt.amount],
            cost_logger=cost_logger,
            cost_log_msg="Cat melt by singleton",
        )
