from __future__ import annotations

import pytest
from clvm_tools import binutils

from chia.types.announcement import Announcement
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.condition_tools import parse_sexp_to_conditions
from chia.wallet.puzzles.load_clvm import load_clvm

SINGLETON_MOD = load_clvm("singleton_top_layer.clsp")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clsp")
P2_SINGLETON_MOD = load_clvm("p2_singleton.clsp")
POOL_MEMBER_MOD = load_clvm("pool_member_innerpuz.clsp", package_or_requirement="chia.pools.puzzles")
POOL_WAITINGROOM_MOD = load_clvm("pool_waitingroom_innerpuz.clsp", package_or_requirement="chia.pools.puzzles")

LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()

LAUNCHER_ID = Program.to(b"launcher-id").get_tree_hash()
POOL_REWARD_PREFIX_MAINNET = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a00000000000000000000000000000000")


def singleton_puzzle(launcher_id: Program, launcher_puzzle_hash: bytes32, inner_puzzle: Program) -> Program:
    return SINGLETON_MOD.curry((SINGLETON_MOD_HASH, (launcher_id, launcher_puzzle_hash)), inner_puzzle)


def p2_singleton_puzzle(launcher_id: Program, launcher_puzzle_hash: bytes32) -> Program:
    return P2_SINGLETON_MOD.curry(SINGLETON_MOD_HASH, launcher_id, launcher_puzzle_hash)


def singleton_puzzle_hash(launcher_id: Program, launcher_puzzle_hash: bytes32, inner_puzzle: Program) -> bytes32:
    return singleton_puzzle(launcher_id, launcher_puzzle_hash, inner_puzzle).get_tree_hash()


def p2_singleton_puzzle_hash(launcher_id: Program, launcher_puzzle_hash: bytes32) -> bytes32:
    return p2_singleton_puzzle(launcher_id, launcher_puzzle_hash).get_tree_hash()


def test_only_odd_coins():
    singleton_mod_hash = SINGLETON_MOD.get_tree_hash()
    # (SINGLETON_STRUCT INNER_PUZZLE lineage_proof my_amount inner_solution)
    # SINGLETON_STRUCT = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    solution = Program.to(
        [
            (singleton_mod_hash, (LAUNCHER_ID, LAUNCHER_PUZZLE_HASH)),
            Program.to(binutils.assemble("(q (51 0xcafef00d 200))")),
            [0xDEADBEEF, 0xCAFEF00D, 200],
            200,
            [],
        ]
    )

    with pytest.raises(Exception) as exception_info:
        cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)
    assert exception_info.value.args == ("clvm raise", "80")

    solution = Program.to(
        [
            (singleton_mod_hash, (LAUNCHER_ID, LAUNCHER_PUZZLE_HASH)),
            Program.to(binutils.assemble("(q (51 0xcafef00d 201))")),
            [0xDEADBEEF, 0xCAFED00D, 210],
            205,
            0,
        ]
    )
    cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)


def test_only_one_odd_coin_created():
    singleton_mod_hash = SINGLETON_MOD.get_tree_hash()
    solution = Program.to(
        [
            (singleton_mod_hash, (LAUNCHER_ID, LAUNCHER_PUZZLE_HASH)),
            Program.to(binutils.assemble("(q (51 0xcafef00d 203) (51 0xfadeddab 205))")),
            [0xDEADBEEF, 0xCAFEF00D, 411],
            411,
            [],
        ]
    )

    with pytest.raises(Exception) as exception_info:
        cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)
    assert exception_info.value.args == ("clvm raise", "80")

    solution = Program.to(
        [
            (singleton_mod_hash, (LAUNCHER_ID, LAUNCHER_PUZZLE_HASH)),
            Program.to(binutils.assemble("(q (51 0xcafef00d 203) (51 0xfadeddab 204) (51 0xdeadbeef 202))")),
            [0xDEADBEEF, 0xCAFEF00D, 411],
            411,
            [],
        ]
    )
    cost, result = SINGLETON_MOD.run_with_cost(INFINITE_COST, solution)


def test_p2_singleton():
    # create a singleton. This should call driver code.
    launcher_id = LAUNCHER_ID
    innerpuz = Program.to(1)
    singleton_full_puzzle = singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH, innerpuz)

    # create a fake coin id for the `p2_singleton`
    p2_singleton_coin_id = Program.to(["test_hash"]).get_tree_hash()
    expected_announcement = Announcement(singleton_full_puzzle.get_tree_hash(), p2_singleton_coin_id).name()

    # create a `p2_singleton` puzzle. This should call driver code.
    p2_singleton_full = p2_singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH)
    solution = Program.to([innerpuz.get_tree_hash(), p2_singleton_coin_id])
    cost, result = p2_singleton_full.run_with_cost(INFINITE_COST, solution)
    conditions = parse_sexp_to_conditions(result)

    p2_singleton_full = p2_singleton_puzzle(launcher_id, LAUNCHER_PUZZLE_HASH)
    solution = Program.to([innerpuz.get_tree_hash(), p2_singleton_coin_id])
    cost, result = p2_singleton_full.run_with_cost(INFINITE_COST, solution)
    assert result.first().rest().first().as_atom() == expected_announcement
    assert conditions[0].vars[0] == expected_announcement
