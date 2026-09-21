from __future__ import annotations

from unittest import mock

import pytest
from chia_rs import AugSchemeMPL, Coin
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.program import Program
from chia.wallet.conditions import CreateCoin, Remark
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE,
    DEFAULT_HIDDEN_PUZZLE_HASH,
    MOD,
    calculate_synthetic_public_key,
)
from chia.wallet.puzzles.puzzle_drivers import (
    ACS,
    ACS_PH,
    ACSPuzzle,
    ACSSolution,
    NilPuzzle,
    NilSolution,
    P2Conditions,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.puzzles.standard_puzzle_drivers import (
    HiddenPuzzleInfo,
    StandardPuzzle,
    StandardPuzzleSolution,
    StandardXCHCoin,
)


def test_standard_puzzle_drivers() -> None:
    original_public_key = AugSchemeMPL.key_gen(bytes([1] * 32)).get_g1()
    synthetic_public_key = calculate_synthetic_public_key(original_public_key, DEFAULT_HIDDEN_PUZZLE_HASH)
    parent_id = bytes32(bytes([2] * 32))
    amount = uint64(1000)

    with pytest.raises(ValueError, match="Must specify either the synthetic or original pubkey"):
        StandardPuzzle()

    from_original = StandardPuzzle(pre_known_original_public_key=original_public_key)
    assert from_original.synthetic_public_key == synthetic_public_key
    from_synthetic = StandardPuzzle(pre_known_synthetic_public_key=synthetic_public_key)
    assert from_synthetic.tree_hash == from_original.tree_hash

    custom_hidden = ACSPuzzle().program
    custom_hidden_info = HiddenPuzzleInfo(program=custom_hidden, pre_computed_puzzle_hash=None)
    custom_synthetic = calculate_synthetic_public_key(original_public_key, custom_hidden.get_tree_hash())
    from_custom_hidden = StandardPuzzle(
        pre_known_original_public_key=original_public_key,
        hidden_puzzle_info=custom_hidden_info,
    )
    assert from_custom_hidden.synthetic_public_key == custom_synthetic
    assert from_custom_hidden.hidden_puzzle_info.tree_hash == custom_hidden.get_tree_hash()

    assert StandardPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=ACSPuzzle().program)) is None
    assert (
        StandardPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=MOD.curry(synthetic_public_key, Program.to(2))))
        is None
    )

    matched_without_solution = StandardPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=from_synthetic.program))
    assert matched_without_solution is not None
    assert matched_without_solution.pre_known_synthetic_public_key == synthetic_public_key
    assert matched_without_solution.pre_known_original_public_key is None
    assert matched_without_solution.hidden_puzzle_info.program == DEFAULT_HIDDEN_PUZZLE

    with mock.patch.object(UnknownPuzzle, "curried_args", new_callable=mock.PropertyMock, return_value=None):
        assert StandardPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=from_synthetic.program)) is None

    delegated_reveal = P2Conditions(conditions=[Remark(Program.to("delegated"))]).program
    delegated_solution = NilSolution().program
    solution_without_original = StandardPuzzleSolution(
        delegated_puzzle=delegated_reveal,
        delegated_solution=delegated_solution,
    )
    matched_delegated = StandardPuzzle.match(
        unknown_puzzle=UnknownPuzzle(known_puzzle=from_synthetic.program),
    )
    assert matched_delegated is not None
    assert matched_delegated.pre_known_original_public_key is None
    assert matched_delegated.hidden_puzzle_info.program == DEFAULT_HIDDEN_PUZZLE

    hidden_reveal = ACSPuzzle().program
    solution_with_original = StandardPuzzleSolution(
        original_public_key=original_public_key,
        delegated_puzzle=hidden_reveal,
        delegated_solution=Program.to([42]),
    )
    matched_hidden = StandardPuzzle.match(
        unknown_puzzle=UnknownPuzzle(known_puzzle=from_synthetic.program),
    )
    assert matched_hidden is not None
    assert matched_hidden.pre_known_synthetic_public_key == synthetic_public_key
    assert matched_hidden.pre_known_original_public_key == original_public_key
    assert matched_hidden.hidden_puzzle_info.program == hidden_reveal
    assert matched_hidden.hidden_puzzle_info.pre_computed_puzzle_hash is None
    assert matched_hidden.hidden_puzzle_info.tree_hash == hidden_reveal.get_tree_hash()

    assert StandardPuzzleSolution.match(unknown_solution=UnknownSolution(Program.to(1))) is None
    assert StandardPuzzleSolution.match(unknown_solution=UnknownSolution(Program.to([1, 2]))) is None
    assert StandardPuzzleSolution.match(unknown_solution=UnknownSolution(Program.to([1, 2, 3, 4]))) is None

    matched_solution_nil_key = StandardPuzzleSolution.match(
        unknown_solution=UnknownSolution(solution_without_original.program)
    )
    assert matched_solution_nil_key is not None
    assert matched_solution_nil_key.original_public_key is None
    assert matched_solution_nil_key.delegated_puzzle == delegated_reveal
    assert matched_solution_nil_key.delegated_solution == delegated_solution

    matched_solution_with_key = StandardPuzzleSolution.match(
        unknown_solution=UnknownSolution(solution_with_original.program)
    )
    assert matched_solution_with_key is not None
    assert matched_solution_with_key.original_public_key == original_public_key
    assert matched_solution_with_key.delegated_puzzle == hidden_reveal
    assert matched_solution_with_key.delegated_solution == Program.to([42])

    coin = Coin(parent_id, from_original.tree_hash, amount)
    xch_coin = StandardXCHCoin(coin=coin, pre_known_original_public_key=original_public_key)
    create_coin = CreateCoin(bytes32(bytes([3] * 32)), uint64(500))
    remark = Remark(Program.to("hi"))
    condition_solution = StandardPuzzleSolution.for_conditions([create_coin, remark])
    expected_delegated = P2Conditions(conditions=[create_coin, remark]).program
    assert StandardPuzzleSolution.match(
        unknown_solution=UnknownSolution(condition_solution.program)
    ) == StandardPuzzleSolution(
        delegated_puzzle=expected_delegated,
        delegated_solution=NilSolution().program,
    )

    synthetic_only_coin = StandardXCHCoin(coin=coin, pre_known_synthetic_public_key=synthetic_public_key)
    with pytest.raises(ValueError, match="Must set `pre_known_original_public_key`"):
        synthetic_only_coin.hidden_puzzle_solution(NilSolution().program)

    hidden_solution = xch_coin.hidden_puzzle_solution(Program.to([99]))
    assert StandardPuzzleSolution.match(
        unknown_solution=UnknownSolution(hidden_solution.program)
    ) == StandardPuzzleSolution(
        original_public_key=original_public_key,
        delegated_puzzle=DEFAULT_HIDDEN_PUZZLE,
        delegated_solution=Program.to([99]),
    )


def test_p2_conditions() -> None:
    create_coin = CreateCoin(bytes32([1] * 32), uint64(500))
    remark = Remark(Program.to("hi"))
    p2 = P2Conditions(conditions=[create_coin, remark])

    assert p2.program == Program.to((1, [create_coin.to_program(), remark.to_program()]))
    assert p2.tree_hash == p2.program.get_tree_hash()
    assert P2Conditions.match(unknown_puzzle=UnknownPuzzle(known_puzzle=p2.program)) == p2
    assert P2Conditions.match(unknown_puzzle=UnknownPuzzle(known_puzzle=ACS)) is None


def test_acs_puzzle() -> None:
    acs = ACSPuzzle()

    assert acs.program == ACS
    assert acs.tree_hash == ACS_PH
    assert ACSPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=ACS)) == ACSPuzzle()
    assert ACSPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=Program.to(2))) is None


def test_acs_solution() -> None:
    create_coin = CreateCoin(bytes32([2] * 32), uint64(1))
    solution = ACSSolution(conditions=[create_coin])

    assert solution.program == Program.to([create_coin.to_program()])
    assert ACSSolution.match(unknown_solution=UnknownSolution(solution.program)) == solution
    assert ACSSolution.match(unknown_solution=UnknownSolution(Program.to(1))) is None


def test_nil_puzzle() -> None:
    nil = NilPuzzle()

    assert nil.program == Program.NIL
    assert nil.tree_hash == Program.NIL.get_tree_hash()
    assert NilPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=Program.NIL)) == NilPuzzle()
    assert NilPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=ACS)) is None


def test_nil_solution() -> None:
    nil = NilSolution()

    assert nil.program == Program.NIL
    assert NilSolution.match(unknown_solution=UnknownSolution(Program.NIL)) == NilSolution()
    assert NilSolution.match(unknown_solution=UnknownSolution(Program.to([1]))) is None
