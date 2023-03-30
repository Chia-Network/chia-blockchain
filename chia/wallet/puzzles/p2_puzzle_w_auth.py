from __future__ import annotations

from typing import Optional, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_LAUNCHER_HASH, SINGLETON_MOD_HASH
from chia.wallet.uncurried_puzzle import UncurriedPuzzle

P2_PUZZLE_WITH_AUTH: Program = load_clvm_maybe_recompile(
    "p2_puzzle_w_auth.clsp", package_or_requirement="chia.wallet.puzzles"
)
DID_PUZZLE_AUTHORIZER: Program = load_clvm_maybe_recompile(
    "did_puzzle_authorizer.clsp", package_or_requirement="chia.wallet.puzzles"
)


def create_p2_puzzle_w_auth(
    auth_func: Program,
    delegated_puzzle: Program,
) -> Program:
    return P2_PUZZLE_WITH_AUTH.curry(
        auth_func,
        delegated_puzzle,
    )


def match_p2_puzzle_w_auth(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[Program, Program]]:
    if uncurried_puzzle.mod == P2_PUZZLE_WITH_AUTH:
        return uncurried_puzzle.args.at("f"), uncurried_puzzle.args.at("rf")
    else:
        return None


def solve_p2_puzzle_w_auth(authorizer_solution: Program, delegated_puzzle_solution: Program) -> Program:
    solution: Program = Program.to(
        [
            authorizer_solution,
            delegated_puzzle_solution,
        ]
    )
    return solution


def create_did_puzzle_authorizer(
    did_id: bytes32,
    singleton_mod_hash: bytes32 = SINGLETON_MOD_HASH,
    singleton_launcher_hash: bytes32 = SINGLETON_LAUNCHER_HASH,
) -> Program:
    return DID_PUZZLE_AUTHORIZER.curry(
        (singleton_mod_hash, (did_id, singleton_launcher_hash)),
    )


def match_did_puzzle_authorizer(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[bytes32]]:
    if uncurried_puzzle.mod == DID_PUZZLE_AUTHORIZER:
        return (bytes32(uncurried_puzzle.args.at("frf").as_python()),)
    else:
        return None


def solve_did_puzzle_authorizer(did_innerpuzhash: bytes32, my_coin_id: bytes32) -> Program:
    solution: Program = Program.to(
        [
            did_innerpuzhash,
            my_coin_id,
        ]
    )
    return solution
