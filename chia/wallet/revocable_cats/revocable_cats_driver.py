from __future__ import annotations


from chia.pools.pool_puzzles import P2_SINGLETON_MOD
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, construct_cat_puzzle
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.singleton import (
    SINGLETON_TOP_LAYER_MOD_HASH,
    SINGLETON_LAUNCHER_PUZZLE_HASH,
)


# Mod
EVERYTHING_WITH_SINGLETON: Program = load_clvm_maybe_recompile(
    "everything_with_singleton.clsp",
    package_or_requirement="chia.wallet.revocable_cats",
    include_standard_libraries=True,
)

REVOCATION_LAYER: Program = load_clvm_maybe_recompile(
    "revocation_layer.clsp",
    package_or_requirement="chia.wallet.revocable_cats",
    include_standard_libraries=True,
)
REVOCATION_LAYER_HASH: bytes32 = REVOCATION_LAYER.get_tree_hash()

P2_DELEGATED_BY_SINGLETON: Program = load_clvm_maybe_recompile(
    "p2_delegated_by_singleton.clsp",
    package_or_requirement="chia.wallet.revocable_cats",
    include_standard_libraries=True,
)


# Basic drivers
def construct_p2_delegated_by_singleton(
    issuer_launcher_id: bytes32, nonce=0
) -> Program:
    singleton_struct: Program = Program.to(
        (
            SINGLETON_TOP_LAYER_MOD_HASH,
            (issuer_launcher_id, SINGLETON_LAUNCHER_PUZZLE_HASH),
        )
    )
    return P2_DELEGATED_BY_SINGLETON.curry(
        SINGLETON_TOP_LAYER_MOD_HASH,
        singleton_struct.get_tree_hash(),
        Program.to(nonce),
    )


def solve_p2_delegated_by_singleton(
    singleton_inner_puzzle_hash: bytes32,
    delegated_puzzle: Program,
    delegated_solution: Program,
) -> Program:
    return Program.to(
        [
            singleton_inner_puzzle_hash,
            delegated_puzzle,
            delegated_solution,
        ]
    )


def construct_everything_with_singleton_cat_tail(
    issuer_launcher_id: bytes32, nonce: int
) -> Program:
    singleton_struct: Program = Program.to(
        (
            SINGLETON_TOP_LAYER_MOD_HASH,
            (issuer_launcher_id, SINGLETON_LAUNCHER_PUZZLE_HASH),
        )
    )
    return EVERYTHING_WITH_SINGLETON.curry(
        SINGLETON_TOP_LAYER_MOD_HASH,
        singleton_struct.get_tree_hash(),
        Program.to(nonce),
    )


def construct_revocation_layer(
    hidden_puzzle_hash: bytes32, inner_puzzle_hash: bytes32
) -> Program:
    return REVOCATION_LAYER.curry(
        REVOCATION_LAYER_HASH, hidden_puzzle_hash, inner_puzzle_hash
    )


def solve_revocation_layer(
    puzzle_reveal: Program, inner_solution: Program, hidden: bool = False
) -> Program:
    solution: Program = Program.to(
        [
            hidden,
            puzzle_reveal,
            inner_solution,
        ]
    )
    return solution


def construct_revocable_cat_inner_puzzle(
    issuer_launcher_id: bytes32,
    inner_puzzle_hash: bytes32,
) -> Program:
    hidden_puzzle_hash = construct_p2_delegated_by_singleton(
        issuer_launcher_id
    ).get_tree_hash()
    revocation_layer = construct_revocation_layer(hidden_puzzle_hash, inner_puzzle_hash)

    return revocation_layer
