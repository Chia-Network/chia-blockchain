from __future__ import annotations

from typing import Iterable, List, Tuple

from chia_rs import AugSchemeMPL, G1Element, G2Element

from chia._tests.util.key_tool import KeyTool
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.spend_bundle import SpendBundle
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.puzzles import (
    p2_conditions,
    p2_delegated_conditions,
    p2_delegated_puzzle,
    p2_delegated_puzzle_or_hidden_puzzle,
    p2_m_of_n_delegate_direct,
    p2_puzzle_hash,
)
from chia.wallet.puzzles.puzzle_utils import make_create_coin_condition

from ..core.make_block_generator import int_to_public_key
from .coin_store import CoinStore, CoinTimestamp

T1 = CoinTimestamp(1, uint32(10000000))
T2 = CoinTimestamp(5, uint32(10003000))

MAX_BLOCK_COST_CLVM = int(1e18)


def secret_exponent_for_index(index: int) -> int:
    blob = index.to_bytes(32, "big")
    hashed_blob = AugSchemeMPL.key_gen(std_hash(b"foo" + blob))
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

    coin_db = CoinStore(DEFAULT_CONSTANTS)

    puzzle_hash = puzzle_reveal.get_tree_hash()

    # farm it
    coin = coin_db.farm_coin(puzzle_hash, farm_time)

    # spend it
    coin_spend = make_spend(coin, puzzle_reveal, solution)

    spend_bundle = SpendBundle([coin_spend], G2Element())
    coin_db.update_coin_store_for_spend_bundle(spend_bundle, spend_time, MAX_BLOCK_COST_CLVM)

    # ensure all outputs are there
    for puzzle_hash, amount in payments:
        for coin in coin_db.coins_for_puzzle_hash(puzzle_hash):
            if coin.amount == amount:
                break
        else:
            assert 0

    # make sure we can actually sign the solution
    signatures: List[G2Element] = []
    for coin_spend in spend_bundle.coin_spends:
        signature = key_lookup.signature_for_solution(coin_spend, bytes([2] * 32))
        signatures.append(signature)
    return SpendBundle(spend_bundle.coin_spends, AugSchemeMPL.aggregate(signatures))


def default_payments_and_conditions(
    initial_index: int, key_lookup: KeyTool
) -> Tuple[List[Tuple[bytes32, int]], Program]:
    # the coin we get from coin_db.farm_coin only has amount 1024, so we can
    # only make small payments to avoid failing with MINTING_COIN
    payments = [
        (throwaway_puzzle_hash(initial_index + 1, key_lookup), initial_index * 10),
        (throwaway_puzzle_hash(initial_index + 2, key_lookup), (initial_index + 1) * 10),
    ]
    conditions = Program.to([make_create_coin_condition(ph, uint64(amount), []) for ph, amount in payments])
    return payments, conditions


def test_p2_conditions():
    key_lookup = KeyTool()
    payments, conditions = default_payments_and_conditions(1, key_lookup)

    puzzle = p2_conditions.puzzle_for_conditions(conditions)
    solution = p2_conditions.solution_for_conditions(conditions)

    do_test_spend(puzzle, solution, payments, key_lookup)


def test_p2_delegated_conditions():
    key_lookup = KeyTool()
    payments, conditions = default_payments_and_conditions(1, key_lookup)

    pk = public_key_for_index(1, key_lookup)

    puzzle = p2_delegated_conditions.puzzle_for_pk(pk)
    solution = p2_delegated_conditions.solution_for_conditions(conditions)

    do_test_spend(puzzle, solution, payments, key_lookup)


def test_p2_delegated_puzzle_simple():
    key_lookup = KeyTool()
    payments, conditions = default_payments_and_conditions(1, key_lookup)

    pk = public_key_for_index(1, key_lookup)

    puzzle = p2_delegated_puzzle.puzzle_for_pk(pk)
    solution = p2_delegated_puzzle.solution_for_conditions(conditions)

    do_test_spend(puzzle, solution, payments, key_lookup)


def test_p2_delegated_puzzle_graftroot():
    key_lookup = KeyTool()
    payments, conditions = default_payments_and_conditions(1, key_lookup)

    delegated_puzzle = p2_delegated_conditions.puzzle_for_pk(public_key_for_index(8, key_lookup))
    delegated_solution = p2_delegated_conditions.solution_for_conditions(conditions)

    puzzle_program = p2_delegated_puzzle.puzzle_for_pk(public_key_for_index(1, key_lookup))
    solution = p2_delegated_puzzle.solution_for_delegated_puzzle(delegated_puzzle, delegated_solution)

    do_test_spend(puzzle_program, solution, payments, key_lookup)


def test_p2_puzzle_hash():
    key_lookup = KeyTool()
    payments, conditions = default_payments_and_conditions(1, key_lookup)

    inner_puzzle = p2_delegated_conditions.puzzle_for_pk(public_key_for_index(4, key_lookup))
    inner_solution = p2_delegated_conditions.solution_for_conditions(conditions)
    inner_puzzle_hash = inner_puzzle.get_tree_hash()

    puzzle_program = p2_puzzle_hash.puzzle_for_inner_puzzle_hash(inner_puzzle_hash)
    assert puzzle_program == p2_puzzle_hash.puzzle_for_inner_puzzle(inner_puzzle)
    solution = p2_puzzle_hash.solution_for_inner_puzzle_and_inner_solution(inner_puzzle, inner_solution)

    do_test_spend(puzzle_program, solution, payments, key_lookup)


def test_p2_m_of_n_delegated_puzzle():
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


def test_p2_delegated_puzzle_or_hidden_puzzle_with_hidden_puzzle():
    key_lookup = KeyTool()
    payments, conditions = default_payments_and_conditions(1, key_lookup)

    hidden_puzzle = p2_conditions.puzzle_for_conditions(conditions)
    hidden_public_key = public_key_for_index(10, key_lookup)

    puzzle = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_public_key_and_hidden_puzzle(
        G1Element.from_bytes_unchecked(hidden_public_key), hidden_puzzle
    )
    solution = p2_delegated_puzzle_or_hidden_puzzle.solution_for_hidden_puzzle(
        G1Element.from_bytes_unchecked(hidden_public_key), hidden_puzzle, Program.to(0)
    )

    do_test_spend(puzzle, solution, payments, key_lookup)


def do_test_spend_p2_delegated_puzzle_or_hidden_puzzle_with_delegated_puzzle(hidden_pub_key_index):
    key_lookup = KeyTool()
    payments, conditions = default_payments_and_conditions(1, key_lookup)

    hidden_puzzle = p2_conditions.puzzle_for_conditions(conditions)
    hidden_public_key = public_key_for_index(hidden_pub_key_index, key_lookup)
    hidden_pub_key_point = G1Element.from_bytes(hidden_public_key)

    puzzle = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_public_key_and_hidden_puzzle(
        hidden_pub_key_point, hidden_puzzle
    )
    payable_payments, payable_conditions = default_payments_and_conditions(5, key_lookup)

    delegated_puzzle = p2_conditions.puzzle_for_conditions(payable_conditions)
    delegated_solution = []

    synthetic_public_key = p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_public_key(
        G1Element.from_bytes(hidden_public_key), hidden_puzzle.get_tree_hash()
    )

    solution = p2_delegated_puzzle_or_hidden_puzzle.solution_for_delegated_puzzle(delegated_puzzle, delegated_solution)

    hidden_puzzle_hash = hidden_puzzle.get_tree_hash()
    synthetic_offset = p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_offset(
        hidden_pub_key_point, hidden_puzzle_hash
    )

    assert synthetic_public_key == int_to_public_key(synthetic_offset) + hidden_pub_key_point

    secret_exponent = key_lookup.dict[G1Element.from_bytes(hidden_public_key)]
    assert int_to_public_key(secret_exponent) == hidden_pub_key_point

    synthetic_secret_exponent = secret_exponent + synthetic_offset
    key_lookup.add_secret_exponents([synthetic_secret_exponent])

    do_test_spend(puzzle, solution, payable_payments, key_lookup)


def test_p2_delegated_puzzle_or_hidden_puzzle_with_delegated_puzzle():
    for hidden_pub_key_index in range(1, 10):
        do_test_spend_p2_delegated_puzzle_or_hidden_puzzle_with_delegated_puzzle(hidden_pub_key_index)
