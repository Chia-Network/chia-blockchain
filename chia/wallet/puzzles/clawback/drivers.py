from __future__ import annotations

import logging
from typing import Any, List, Optional, Set, Union

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.condition_tools import conditions_for_solution
from chia.util.ints import uint64
from chia.util.misc import VersionedBlob
from chia.wallet.puzzles.clawback.metadata import ClawbackMetadata
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import MOD
from chia.wallet.uncurried_puzzle import UncurriedPuzzle
from chia.wallet.util.curry_and_treehash import calculate_hash_of_quoted_mod_hash, curry_and_treehash
from chia.wallet.util.merkle_tree import MerkleTree
from chia.wallet.util.wallet_types import RemarkDataType

P2_1_OF_N = load_clvm_maybe_recompile("p2_1_of_n.clsp")
P2_CURRIED_PUZZLE_MOD = load_clvm_maybe_recompile("p2_puzzle_hash.clsp")
P2_CURRIED_PUZZLE_MOD_HASH_QUOTED = calculate_hash_of_quoted_mod_hash(P2_CURRIED_PUZZLE_MOD.get_tree_hash())
AUGMENTED_CONDITION = load_clvm_maybe_recompile("augmented_condition.clsp")
AUGMENTED_CONDITION_HASH = AUGMENTED_CONDITION.get_tree_hash()
log = logging.getLogger(__name__)


def create_augmented_cond_puzzle(condition: List[Union[int, uint64]], puzzle: Program) -> Program:
    return AUGMENTED_CONDITION.curry(condition, puzzle)


def create_augmented_cond_puzzle_hash(condition: List[Any], puzzle_hash: bytes32) -> bytes32:
    hash_of_quoted_mod_hash = calculate_hash_of_quoted_mod_hash(AUGMENTED_CONDITION_HASH)
    hashed_args = [Program.to(condition).get_tree_hash(), puzzle_hash]
    return curry_and_treehash(hash_of_quoted_mod_hash, *hashed_args)


def create_augmented_cond_solution(inner_solution: Program) -> Program:
    solution: Program = Program.to([inner_solution])
    return solution


def create_p2_puzzle_hash_puzzle(puzzle_hash: bytes32) -> Program:
    return P2_CURRIED_PUZZLE_MOD.curry(puzzle_hash)


def create_p2_puzzle_hash_solution(inner_puzzle: Program, inner_solution: Program) -> Program:
    solution: Program = Program.to([inner_puzzle, inner_solution])
    return solution


def create_clawback_merkle_tree(timelock: uint64, sender_ph: bytes32, recipient_ph: bytes32) -> MerkleTree:
    """
    Returns a merkle tree object
    For clawbacks there are only 2 puzzles in the merkle tree, claim puzzle and clawback puzzle
    """
    if timelock < 1:
        raise ValueError("Timelock must be at least 1 second")
    timelock_condition = [ConditionOpcode.ASSERT_SECONDS_RELATIVE, timelock]
    augmented_cond_puz_hash = create_augmented_cond_puzzle_hash(timelock_condition, recipient_ph)
    merkle_tree = MerkleTree(
        [
            augmented_cond_puz_hash,
            curry_and_treehash(P2_CURRIED_PUZZLE_MOD_HASH_QUOTED, Program.to(sender_ph).get_tree_hash()),
        ]
    )
    return merkle_tree


def create_merkle_proof(merkle_tree: MerkleTree, puzzle_hash: bytes32) -> Program:
    """
    To spend a p2_1_of_n clawback we recreate the full merkle tree
    The required proof is then selected from the merkle tree based on the puzzle_hash of the puzzle we
    want to execute
    Returns a proof: (int, List[bytes32]) which can be provided to the p2_1_of_n solution
    """
    proof = merkle_tree.generate_proof(puzzle_hash)
    program: Program = Program.to((proof[0], proof[1][0]))
    return program


def create_merkle_puzzle(timelock: uint64, sender_ph: bytes32, recipient_ph: bytes32) -> Program:
    merkle_tree = create_clawback_merkle_tree(timelock, sender_ph, recipient_ph)
    puzzle: Program = P2_1_OF_N.curry(merkle_tree.calculate_root())
    return puzzle


def create_merkle_solution(
    timelock: uint64,
    sender_ph: bytes32,
    recipient_ph: bytes32,
    inner_puzzle: Program,
    inner_solution: Program,
) -> Program:
    """
    Recreates the full merkle tree of a p2_1_of_n clawback coin. It uses the timelock and each party's
    puzhash to create the tree.
    The provided inner puzzle must hash to match either the sender or recipient puzhash
    If it's the sender, then create the clawback solution. If it's the recipient then create the claim
    solution.
    Returns a program which is the solution to a p2_1_of_n clawback.
    """
    merkle_tree = create_clawback_merkle_tree(timelock, sender_ph, recipient_ph)
    inner_puzzle_hash = inner_puzzle.get_tree_hash()
    if inner_puzzle_hash == sender_ph:
        cb_inner_puz = create_p2_puzzle_hash_puzzle(sender_ph)
        merkle_proof = create_merkle_proof(merkle_tree, cb_inner_puz.get_tree_hash())
        cb_inner_solution = create_p2_puzzle_hash_solution(inner_puzzle, inner_solution)
    elif inner_puzzle_hash == recipient_ph:
        condition = [80, timelock]
        cb_inner_puz = create_augmented_cond_puzzle(condition, inner_puzzle)
        merkle_proof = create_merkle_proof(merkle_tree, cb_inner_puz.get_tree_hash())
        cb_inner_solution = create_augmented_cond_solution(inner_solution)
    else:
        raise ValueError("Invalid Clawback inner puzzle.")
    solution: Program = Program.to([merkle_proof, cb_inner_puz, cb_inner_solution])
    return solution


def match_clawback_puzzle(
    uncurried: UncurriedPuzzle, inner_puzzle: Program, inner_solution: Program
) -> Optional[ClawbackMetadata]:
    # Check if the inner puzzle is a P2 puzzle
    if MOD != uncurried.mod:
        return None
    # Fetch Remark condition
    conditions = conditions_for_solution(
        inner_puzzle,
        inner_solution,
        DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM // 8,
    )
    metadata: Optional[ClawbackMetadata] = None
    new_puzhash: Set[bytes32] = set()
    if conditions is not None:
        for condition in conditions:
            if (
                condition.opcode == ConditionOpcode.REMARK
                and len(condition.vars) == 2
                and int.from_bytes(condition.vars[0], "big") == RemarkDataType.CLAWBACK
            ):
                try:
                    metadata = ClawbackMetadata.from_bytes(VersionedBlob.from_bytes(condition.vars[1]).blob)
                except Exception:
                    # Invalid Clawback metadata
                    log.error(f"Invalid Clawback metadata {condition.vars[1].hex()}")
                    return None
            if condition.opcode == ConditionOpcode.CREATE_COIN:
                new_puzhash.add(bytes32.from_bytes(condition.vars[0]))
    # Check if the inner puzzle matches the coin puzzle hash
    if metadata is None:
        return metadata
    puzzle: Program = create_merkle_puzzle(
        metadata.time_lock, metadata.sender_puzzle_hash, metadata.recipient_puzzle_hash
    )
    if puzzle.get_tree_hash() not in new_puzhash:
        # The metadata doesn't match the inner puzzle, ignore it
        log.error(
            f"Clawback metadata {metadata} doesn't match inner puzzle {inner_puzzle.get_tree_hash().hex()}"
        )  # pragma: no cover
        return None  # pragma: no cover
    return metadata


def generate_clawback_spend_bundle(
    coin: Coin, metadata: ClawbackMetadata, inner_puzzle: Program, inner_solution: Program
) -> CoinSpend:
    time_lock: uint64 = metadata.time_lock
    puzzle: Program = create_merkle_puzzle(time_lock, metadata.sender_puzzle_hash, metadata.recipient_puzzle_hash)
    if puzzle.get_tree_hash() != coin.puzzle_hash:
        raise ValueError(
            f"Cannot spend merkle coin {coin.name()}, "
            f"recreate puzzle hash {puzzle.get_tree_hash().hex()}, actual puzzle hash {coin.puzzle_hash.hex()}"
        )

    solution: Program = create_merkle_solution(
        time_lock, metadata.sender_puzzle_hash, metadata.recipient_puzzle_hash, inner_puzzle, inner_solution
    )
    return CoinSpend(coin, puzzle, solution)
