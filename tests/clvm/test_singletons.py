import copy

from typing import List, Tuple, Optional
from unittest import TestCase

from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_solution import CoinSolution
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import ConditionOpcode
from chia.util.ints import uint64
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles import (
    p2_conditions,
    p2_delegated_puzzle_or_hidden_puzzle,
    singleton_top_layer,
)
from tests.util.key_tool import KeyTool
from tests.clvm.test_puzzles import (
    public_key_for_index,
    secret_exponent_for_index,
)

from .coin_store import CoinStore, CoinTimestamp, BadSpendBundleError

"""
This test suite aims to test:
    - chia.wallet.puzzles.singleton_top_layer.py
    - chia.wallet.puzzles.singleton_top_layer.clvm
    - chia.wallet.puzzles.p2_singleton.clvm
    - chia.wallet.puzzles.p2_singleton_or_delayed_puzhash.clvm
"""

T1 = CoinTimestamp(1, 10000000)


# Helper function
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
def make_and_spend_bundle(
    db: CoinStore,
    coin: Coin,
    delegated_puzzle: Program,
    coinsols: List[CoinSolution],
    exception: Optional[Exception] = None,
    ex_msg: str = "",
    fail_msg: str = "",
):

    signature: G2Element = sign_delegated_puz(delegated_puzzle, coin)
    spend_bundle = SpendBundle(
        coinsols,
        signature,
    )

    try:
        db.update_coin_store_for_spend_bundle(
            spend_bundle,
            T1,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
        )
        if exception is not None:
            raise AssertionError(fail_msg)
    except Exception as e:
        if exception is not None:
            assert type(e) is exception
            assert str(e) == ex_msg
        else:
            raise e


class TestSingleton(TestCase):
    def test_singleton_top_layer(self):
        # START TESTS
        # Generate starting info
        key_lookup = KeyTool()
        pk: G1Element = public_key_for_index(1, key_lookup)
        starting_puzzle: Program = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_pk(pk)  # noqa
        adapted_puzzle: Program = singleton_top_layer.adapt_inner_to_singleton(starting_puzzle)  # noqa
        adapted_puzzle_hash: bytes32 = adapted_puzzle.get_tree_hash()

        # Get our starting standard coin created
        START_AMOUNT: uint64 = 1023
        coin_db = CoinStore()
        coin_db.farm_coin(starting_puzzle.get_tree_hash(), T1, START_AMOUNT)
        starting_coin: Coin = next(coin_db.all_unspent_coins())
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

        starting_coinsol = CoinSolution(
            starting_coin,
            starting_puzzle,
            full_solution,
        )

        make_and_spend_bundle(
            coin_db,
            starting_coin,
            delegated_puzzle,
            [starting_coinsol, launcher_coinsol],
        )

        # EVE
        singleton_eve: Coin = next(coin_db.all_unspent_coins())
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

        singleton_eve_coinsol = CoinSolution(
            singleton_eve,
            puzzle_reveal,
            full_solution,
        )

        make_and_spend_bundle(
            coin_db,
            singleton_eve,
            delegated_puzzle,
            [singleton_eve_coinsol],
        )

        # POST-EVE
        singleton: Coin = next(coin_db.all_unspent_coins())
        # Same delegated_puzzle / inner_solution. We're just recreating ourself
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(singleton_eve_coinsol)  # noqa
        # Same puzzle_reveal too
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof,
            singleton.amount,
            inner_solution,
        )

        singleton_coinsol = CoinSolution(
            singleton,
            puzzle_reveal,
            full_solution,
        )

        make_and_spend_bundle(
            coin_db,
            singleton,
            delegated_puzzle,
            [singleton_coinsol],
        )

        # CLAIM A P2_SINGLETON
        singleton_child: Coin = next(coin_db.all_unspent_coins())
        p2_singleton_puz: Program = singleton_top_layer.pay_to_singleton_puzzle(launcher_id)
        p2_singleton_ph: bytes32 = p2_singleton_puz.get_tree_hash()
        ARBITRARY_AMOUNT: uint64 = 1379
        coin_db.farm_coin(p2_singleton_ph, T1, ARBITRARY_AMOUNT)
        p2_singleton_coin: Coin = list(
            filter(
                lambda e: e.amount == ARBITRARY_AMOUNT,
                list(coin_db.all_unspent_coins()),
            )
        )[0]
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
        singleton_claim_coinsol = CoinSolution(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        make_and_spend_bundle(coin_db, singleton_child, delegated_puzzle, [singleton_claim_coinsol, claim_coinsol])

        # CLAIM A P2_SINGLETON_OR_DELAYED
        singleton_child: Coin = next(coin_db.all_unspent_coins())
        DELAY_TIME: uint64 = 1
        DELAY_PH: bytes32 = adapted_puzzle_hash
        p2_singleton_puz: Program = singleton_top_layer.pay_to_singleton_or_delay_puzzle(
            launcher_id,
            DELAY_TIME,
            DELAY_PH,
        )
        p2_singleton_ph: bytes32 = p2_singleton_puz.get_tree_hash()
        ARBITRARY_AMOUNT: uint64 = 1379
        coin_db.farm_coin(p2_singleton_ph, T1, ARBITRARY_AMOUNT)
        p2_singleton_coin: Coin = list(
            filter(
                lambda e: e.amount == ARBITRARY_AMOUNT,
                list(coin_db.all_unspent_coins()),
            )
        )[0]
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
        delay_claim_coinsol = CoinSolution(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        # Fork it so we can try the other spend types
        fork_coin_db: CoinStore = copy.deepcopy(coin_db)
        fork_coin_db_2: CoinStore = copy.deepcopy(coin_db)
        make_and_spend_bundle(coin_db, singleton_child, delegated_puzzle, [delay_claim_coinsol, claim_coinsol])

        # TRY TO SPEND AWAY TOO SOON (Negative Test)
        to_delay_ph_coinsol = singleton_top_layer.spend_to_delayed_puzzle(
            p2_singleton_coin,
            ARBITRARY_AMOUNT,
            launcher_id,
            DELAY_TIME,
            DELAY_PH,
        )
        try:
            fork_coin_db.update_coin_store_for_spend_bundle(
                SpendBundle([to_delay_ph_coinsol], G2Element()),
                T1,
                DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            )
        except BadSpendBundleError as e:
            assert str(e) == "condition validation failure Err.ASSERT_SECONDS_RELATIVE_FAILED"

        # SPEND TO DELAYED PUZZLE HASH
        fork_coin_db_2.update_coin_store_for_spend_bundle(
            SpendBundle([to_delay_ph_coinsol], G2Element()),
            CoinTimestamp(100, 10000005),
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
        )

        # CREATE MULTIPLE ODD CHILDREN (Negative Test)
        singleton_child: Coin = next(coin_db.all_unspent_coins())
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
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(singleton_coinsol)  # noqa
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_child.amount, inner_solution
        )

        multi_odd_coinsol = CoinSolution(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        make_and_spend_bundle(
            coin_db,
            singleton_child,
            delegated_puzzle,
            [multi_odd_coinsol],
            exception=BadSpendBundleError,
            ex_msg="clvm validation failure Err.SEXP_ERROR",
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
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(singleton_coinsol)  # noqa
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_child.amount, inner_solution
        )

        no_odd_coinsol = CoinSolution(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        make_and_spend_bundle(
            coin_db,
            singleton_child,
            delegated_puzzle,
            [no_odd_coinsol],
            exception=BadSpendBundleError,
            ex_msg="clvm validation failure Err.SEXP_ERROR",
            fail_msg="Need at least one odd child",
        )

        # ATTEMPT TO CREATE AN EVEN SINGLETON (Negative test)
        fork_coin_db: CoinStore = copy.deepcopy(coin_db)

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
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(delay_claim_coinsol)
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_child.amount, inner_solution
        )

        singleton_even_coinsol = CoinSolution(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        make_and_spend_bundle(
            fork_coin_db,
            singleton_child,
            delegated_puzzle,
            [singleton_even_coinsol],
        )

        # Now try a perfectly innocent spend
        evil_coin: Coin = next(fork_coin_db.all_unspent_coins())
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

        evil_coinsol = CoinSolution(
            evil_coin,
            puzzle_reveal,
            full_solution,
        )

        make_and_spend_bundle(
            fork_coin_db,
            evil_coin,
            delegated_puzzle,
            [evil_coinsol],
            exception=BadSpendBundleError,
            ex_msg="condition validation failure Err.ASSERT_MY_COIN_ID_FAILED",
            fail_msg="This coin is even!",
        )

        # MELTING
        # Remember, we're still spending singleton_child
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
        lineage_proof: LineageProof = singleton_top_layer.lineage_proof_for_coinsol(delay_claim_coinsol)
        puzzle_reveal: Program = singleton_top_layer.puzzle_for_singleton(
            launcher_id,
            adapted_puzzle,
        )
        full_solution: Program = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_child.amount, inner_solution
        )

        melt_coinsol = CoinSolution(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        make_and_spend_bundle(
            coin_db,
            singleton_child,
            delegated_puzzle,
            [melt_coinsol],
        )

        melted_coin = next(coin_db.all_unspent_coins())
        assert melted_coin.puzzle_hash == adapted_puzzle_hash
