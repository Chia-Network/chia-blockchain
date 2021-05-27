from typing import Iterable, List, Tuple
from unittest import TestCase

from blspy import AugSchemeMPL, BasicSchemeMPL, G1Element, G2Element, PrivateKey

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_solution import CoinSolution
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import ConditionOpcode
from chia.util.hash import std_hash
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.wallet.puzzles import (
    p2_conditions,
    p2_delegated_conditions,
    p2_delegated_puzzle,
    p2_delegated_puzzle_or_hidden_puzzle,
    p2_m_of_n_delegate_direct,
    p2_puzzle_hash,
    singleton_top_layer,
)
from tests.util.key_tool import KeyTool

from ..core.make_block_generator import int_to_public_key
from .coin_store import CoinStore, CoinTimestamp, BadSpendBundleError

T1 = CoinTimestamp(1, 10000000)
T2 = CoinTimestamp(5, 10003000)

MAX_BLOCK_COST_CLVM = int(1e18)


def secret_exponent_for_index(index: int) -> int:
    blob = index.to_bytes(32, "big")
    hashed_blob = BasicSchemeMPL.key_gen(std_hash(b"foo" + blob))
    r = int.from_bytes(hashed_blob, "big")
    return r


def public_key_for_index(index: int, key_lookup: KeyTool) -> bytes:
    secret_exponent = secret_exponent_for_index(index)
    key_lookup.add_secret_exponents([secret_exponent])
    return bytes(int_to_public_key(secret_exponent))


def throwaway_puzzle_hash(index: int, key_lookup: KeyTool) -> bytes32:
    return p2_delegated_puzzle.puzzle_for_pk(public_key_for_index(index, key_lookup)).get_tree_hash()


def do_test_spend(
    puzzle_reveal: Program,
    solution: Program,
    payments: Iterable[Tuple[bytes32, int]],
    key_lookup: KeyTool,
    farm_time: CoinTimestamp = T1,
    spend_time: CoinTimestamp = T2,
) -> SpendBundle:
    """
    This method will farm a coin paid to the hash of `puzzle_reveal`, then try to spend it
    with `solution`, and verify that the created coins correspond to `payments`.

    The `key_lookup` is used to create a signed version of the `SpendBundle`, although at
    this time, signatures are not verified.
    """

    coin_db = CoinStore()

    puzzle_hash = puzzle_reveal.get_tree_hash()

    # farm it
    coin = coin_db.farm_coin(puzzle_hash, farm_time)

    # spend it
    coin_solution = CoinSolution(coin, puzzle_reveal, solution)

    spend_bundle = SpendBundle([coin_solution], G2Element())
    coin_db.update_coin_store_for_spend_bundle(spend_bundle, spend_time, MAX_BLOCK_COST_CLVM)

    # ensure all outputs are there
    for puzzle_hash, amount in payments:
        for coin in coin_db.coins_for_puzzle_hash(puzzle_hash):
            if coin.amount == amount:
                break
        else:
            assert 0

    # make sure we can actually sign the solution
    signatures = []
    for coin_solution in spend_bundle.coin_solutions:
        signature = key_lookup.signature_for_solution(coin_solution, bytes([2] * 32))
        signatures.append(signature)
    return SpendBundle(spend_bundle.coin_solutions, AugSchemeMPL.aggregate(signatures))


def default_payments_and_conditions(
    initial_index: int, key_lookup: KeyTool
) -> Tuple[List[Tuple[bytes32, int]], Program]:

    payments = [
        (throwaway_puzzle_hash(initial_index + 1, key_lookup), initial_index * 1000),
        (throwaway_puzzle_hash(initial_index + 2, key_lookup), (initial_index + 1) * 1000),
    ]
    conditions = Program.to([make_create_coin_condition(ph, amount) for ph, amount in payments])
    return payments, conditions


def make_create_coin_condition(puzzle_hash, amount):
    return Program.to([ConditionOpcode.CREATE_COIN, puzzle_hash, amount])


class TestPuzzles(TestCase):
    def test_p2_conditions(self):
        key_lookup = KeyTool()
        payments, conditions = default_payments_and_conditions(1, key_lookup)

        puzzle = p2_conditions.puzzle_for_conditions(conditions)
        solution = p2_conditions.solution_for_conditions(conditions)

        do_test_spend(puzzle, solution, payments, key_lookup)

    def test_p2_delegated_conditions(self):
        key_lookup = KeyTool()
        payments, conditions = default_payments_and_conditions(1, key_lookup)

        pk = public_key_for_index(1, key_lookup)

        puzzle = p2_delegated_conditions.puzzle_for_pk(pk)
        solution = p2_delegated_conditions.solution_for_conditions(conditions)

        do_test_spend(puzzle, solution, payments, key_lookup)

    def test_p2_delegated_puzzle_simple(self):
        key_lookup = KeyTool()
        payments, conditions = default_payments_and_conditions(1, key_lookup)

        pk = public_key_for_index(1, key_lookup)

        puzzle = p2_delegated_puzzle.puzzle_for_pk(pk)
        solution = p2_delegated_puzzle.solution_for_conditions(conditions)

        do_test_spend(puzzle, solution, payments, key_lookup)

    def test_p2_delegated_puzzle_graftroot(self):
        key_lookup = KeyTool()
        payments, conditions = default_payments_and_conditions(1, key_lookup)

        delegated_puzzle = p2_delegated_conditions.puzzle_for_pk(public_key_for_index(8, key_lookup))
        delegated_solution = p2_delegated_conditions.solution_for_conditions(conditions)

        puzzle_program = p2_delegated_puzzle.puzzle_for_pk(public_key_for_index(1, key_lookup))
        solution = p2_delegated_puzzle.solution_for_delegated_puzzle(delegated_puzzle, delegated_solution)

        do_test_spend(puzzle_program, solution, payments, key_lookup)

    def test_p2_puzzle_hash(self):
        key_lookup = KeyTool()
        payments, conditions = default_payments_and_conditions(1, key_lookup)

        inner_puzzle = p2_delegated_conditions.puzzle_for_pk(public_key_for_index(4, key_lookup))
        inner_solution = p2_delegated_conditions.solution_for_conditions(conditions)
        inner_puzzle_hash = inner_puzzle.get_tree_hash()

        puzzle_program = p2_puzzle_hash.puzzle_for_inner_puzzle_hash(inner_puzzle_hash)
        assert puzzle_program == p2_puzzle_hash.puzzle_for_inner_puzzle(inner_puzzle)
        solution = p2_puzzle_hash.solution_for_inner_puzzle_and_inner_solution(inner_puzzle, inner_solution)

        do_test_spend(puzzle_program, solution, payments, key_lookup)

    def test_p2_m_of_n_delegated_puzzle(self):
        key_lookup = KeyTool()
        payments, conditions = default_payments_and_conditions(1, key_lookup)

        pks = [public_key_for_index(_, key_lookup) for _ in range(1, 6)]
        M = 3

        delegated_puzzle = p2_conditions.puzzle_for_conditions(conditions)
        delegated_solution = []

        puzzle_program = p2_m_of_n_delegate_direct.puzzle_for_m_of_public_key_list(M, pks)
        selectors = [1, [], [], 1, 1]
        solution = p2_m_of_n_delegate_direct.solution_for_delegated_puzzle(
            M, selectors, delegated_puzzle, delegated_solution
        )

        do_test_spend(puzzle_program, solution, payments, key_lookup)

    def test_p2_delegated_puzzle_or_hidden_puzzle_with_hidden_puzzle(self):
        key_lookup = KeyTool()
        payments, conditions = default_payments_and_conditions(1, key_lookup)

        hidden_puzzle = p2_conditions.puzzle_for_conditions(conditions)
        hidden_public_key = public_key_for_index(10, key_lookup)

        puzzle = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_public_key_and_hidden_puzzle(
            hidden_public_key, hidden_puzzle
        )
        solution = p2_delegated_puzzle_or_hidden_puzzle.solution_for_hidden_puzzle(
            hidden_public_key, hidden_puzzle, Program.to(0)
        )

        do_test_spend(puzzle, solution, payments, key_lookup)

    def do_test_spend_p2_delegated_puzzle_or_hidden_puzzle_with_delegated_puzzle(self, hidden_pub_key_index):
        key_lookup = KeyTool()
        payments, conditions = default_payments_and_conditions(1, key_lookup)

        hidden_puzzle = p2_conditions.puzzle_for_conditions(conditions)
        hidden_public_key = public_key_for_index(hidden_pub_key_index, key_lookup)

        puzzle = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_public_key_and_hidden_puzzle(
            hidden_public_key, hidden_puzzle
        )
        payable_payments, payable_conditions = default_payments_and_conditions(5, key_lookup)

        delegated_puzzle = p2_conditions.puzzle_for_conditions(payable_conditions)
        delegated_solution = []

        synthetic_public_key = p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_public_key(
            hidden_public_key, hidden_puzzle.get_tree_hash()
        )

        solution = p2_delegated_puzzle_or_hidden_puzzle.solution_for_delegated_puzzle(
            delegated_puzzle, delegated_solution
        )

        hidden_puzzle_hash = hidden_puzzle.get_tree_hash()
        synthetic_offset = p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_offset(
            hidden_public_key, hidden_puzzle_hash
        )

        hidden_pub_key_point = G1Element.from_bytes(hidden_public_key)
        assert synthetic_public_key == int_to_public_key(synthetic_offset) + hidden_pub_key_point

        secret_exponent = key_lookup.get(hidden_public_key)
        assert int_to_public_key(secret_exponent) == hidden_pub_key_point

        synthetic_secret_exponent = secret_exponent + synthetic_offset
        key_lookup.add_secret_exponents([synthetic_secret_exponent])

        do_test_spend(puzzle, solution, payable_payments, key_lookup)

    def test_p2_delegated_puzzle_or_hidden_puzzle_with_delegated_puzzle(self):
        for hidden_pub_key_index in range(1, 10):
            self.do_test_spend_p2_delegated_puzzle_or_hidden_puzzle_with_delegated_puzzle(hidden_pub_key_index)

    def test_singleton_top_layer(self):
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

        comment: List[Tuple[str, str]] = [("hello", "world")]  # comments are lists of key value pairs

        # Try to create an even singleton (driver test)
        try:
            conditions, launcher_coinsol = singleton_top_layer.launch_conditions_and_coinsol(  # noqa
                starting_coin, adapted_puzzle, comment, (START_AMOUNT - 1)
            )
            raise AssertionError("This should fail due to an even amount")
        except ValueError as msg:
            assert str(msg) == "The coin amount cannot be even. Subtract one mojo."
            conditions, launcher_coinsol = singleton_top_layer.launch_conditions_and_coinsol(  # noqa
                starting_coin, adapted_puzzle, comment, START_AMOUNT
            )

        # Creating the signature for the standard transaction
        synthetic_secret_key: PrivateKey = p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_secret_key(  # noqa
            PrivateKey.from_bytes(
                secret_exponent_for_index(1).to_bytes(32, "big"),
            ),
            p2_delegated_puzzle_or_hidden_puzzle.DEFAULT_HIDDEN_PUZZLE_HASH,
        )

        # Creating solution for standard transaction
        delegated_puzzle: Program = p2_conditions.puzzle_for_conditions(conditions)
        solution: Program = p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(conditions) # noqa

        #Signing the delegated puzzle
        signature: G2Element = AugSchemeMPL.sign(
            synthetic_secret_key,
            (
                delegated_puzzle.get_tree_hash()
                + starting_coin.name()
                + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA
            ),
        )

        # Bring it all together into a spend bundle
        spend_bundle = SpendBundle(
            [
                CoinSolution(
                    starting_coin,
                    starting_puzzle,
                    solution,
                ),
                launcher_coinsol,  # Spending the launcher also
            ],
            signature,
        )

        # Attempt to "spend" the spend bundle
        coin_db.update_coin_store_for_spend_bundle(
            spend_bundle,
            T1,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
        )

        # Eve spend
        singleton_eve = next(coin_db.all_unspent_coins())
        launcher_coin = singleton_top_layer.generate_launcher_coin(
            starting_coin, START_AMOUNT
        )
        launcher_id = launcher_coin.name()
        # This delegated puzzle just recreates the coin exactly
        delegated_puzzle = Program.to(
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
        inner_solution = Program.to([[], delegated_puzzle, []])
        # Generate the lineage proof we will need from the launcher coin
        lineage_proof = singleton_top_layer.lineage_proof_for_coinsol(launcher_coinsol) # noqa
        puzzle_reveal = singleton_top_layer.puzzle_for_singleton(
            launcher_id, adapted_puzzle,
        )
        full_solution = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_eve.amount, inner_solution
        )

        # Sign the delegated_puzzle
        signature = AugSchemeMPL.sign(
            synthetic_secret_key,
            (
                delegated_puzzle.get_tree_hash()
                + singleton_eve.name()
                + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA  # noqa
            ),
        )

        singleton_eve_coinsol = CoinSolution(
            singleton_eve,
            puzzle_reveal,
            full_solution,
        )

        spend_bundle = SpendBundle(
            [singleton_eve_coinsol],
            signature,
        )

        coin_db.update_coin_store_for_spend_bundle(
            spend_bundle,
            T1,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
        )

        # Post-eve spend
        singleton = next(coin_db.all_unspent_coins())
        # Same delegated_puzzle / inner_solution. We're just recreating ourself
        lineage_proof = singleton_top_layer.lineage_proof_for_coinsol(singleton_eve_coinsol) # noqa
        # Same puzzle_reveal too
        full_solution = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton.amount, inner_solution
        )
        signature = AugSchemeMPL.sign(
            synthetic_secret_key,
            (
                delegated_puzzle.get_tree_hash()
                + singleton.name()
                + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA  # noqa
            ),
        )

        singleton_coinsol = CoinSolution(
            singleton,
            puzzle_reveal,
            full_solution,
        )

        spend_bundle = SpendBundle(
            [singleton_coinsol],
            signature,
        )

        coin_db.update_coin_store_for_spend_bundle(
            spend_bundle,
            T1,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
        )

        # Try to spend multiple odd amounts
        singleton_child = next(coin_db.all_unspent_coins())
        delegated_puzzle = Program.to(
            (
                1,
                [
                    [ConditionOpcode.CREATE_COIN, adapted_puzzle_hash, 3],
                    [ConditionOpcode.CREATE_COIN, adapted_puzzle_hash, 7],
                ],
            )
        )
        inner_solution = Program.to([[], delegated_puzzle, []])
        lineage_proof = singleton_top_layer.lineage_proof_for_coinsol(singleton_coinsol) # noqa
        puzzle_reveal = singleton_top_layer.puzzle_for_singleton(
            launcher_id, adapted_puzzle,
        )
        full_solution = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_child.amount, inner_solution
        )
        signature = AugSchemeMPL.sign(
            synthetic_secret_key,
            (
                delegated_puzzle.get_tree_hash()
                + singleton_child.name()
                + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA  # noqa
            ),
        )

        multi_odd_coinsol = CoinSolution(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        spend_bundle = SpendBundle(
            [multi_odd_coinsol],
            signature
        )

        try:
            coin_db.update_coin_store_for_spend_bundle(
                spend_bundle,
                T1,
                DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            )
            raise AssertionError("Creating more than one singleton!")
        except BadSpendBundleError as msg:
            assert str(msg) == 'clvm validation failure Err.SEXP_ERROR'
            pass

        # Try to spend no odd outputs
        delegated_puzzle = Program.to(
            (
                1,
                [
                    [ConditionOpcode.CREATE_COIN, adapted_puzzle_hash, 4],
                    [ConditionOpcode.CREATE_COIN, adapted_puzzle_hash, 10],
                ],
            )
        )
        inner_solution = Program.to([[], delegated_puzzle, []])
        lineage_proof = singleton_top_layer.lineage_proof_for_coinsol(singleton_coinsol) # noqa
        puzzle_reveal = singleton_top_layer.puzzle_for_singleton(
            launcher_id, adapted_puzzle,
        )
        full_solution = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_child.amount, inner_solution
        )
        signature = AugSchemeMPL.sign(
            synthetic_secret_key,
            (
                delegated_puzzle.get_tree_hash()
                + singleton_child.name()
                + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA  # noqa
            ),
        )

        multi_odd_coinsol = CoinSolution(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        spend_bundle = SpendBundle(
            [multi_odd_coinsol],
            signature
        )

        try:
            coin_db.update_coin_store_for_spend_bundle(
                spend_bundle,
                T1,
                DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            )
            raise AssertionError("Creating even coins only!")
        except BadSpendBundleError as msg:
            assert str(msg) == 'clvm validation failure Err.SEXP_ERROR'
            pass

        # Test melting
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
        inner_solution: Program = p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(conditions) # noqa
        # Same lineage_proof / puzzle reveal as failure case above
        full_solution = singleton_top_layer.solution_for_singleton(
            lineage_proof, singleton_child.amount, inner_solution
        )
        signature = AugSchemeMPL.sign(
            synthetic_secret_key,
            (
                delegated_puzzle.get_tree_hash()
                + singleton_child.name()
                + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA  # noqa
            ),
        )

        melt_coinsol = CoinSolution(
            singleton_child,
            puzzle_reveal,
            full_solution,
        )

        spend_bundle = SpendBundle(
            [melt_coinsol],
            signature
        )

        coin_db.update_coin_store_for_spend_bundle(
            spend_bundle,
            T1,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
        )

        melted_coin = next(coin_db.all_unspent_coins())

        assert melted_coin.puzzle_hash == adapted_puzzle_hash  # noqa
