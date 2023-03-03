from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.condition_tools import conditions_for_solution
from chia.util.ints import uint64
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import MOD
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.merkle_utils import build_merkle_tree
from chia.wallet.util.puzzle_decorator_type import PuzzleDecoratorType

P2_1_OF_N = load_clvm_maybe_recompile("p2_1_of_n.clvm")
P2_CURRIED_PUZZLE_HASH = load_clvm_maybe_recompile("p2_puzzle_hash.clvm")
AUGMENTED_CONDITION = load_clvm_maybe_recompile("augmented_condition.clvm")


def create_augmented_cond_puzzle(condition: List[Any], puzzle_hash: bytes32) -> Any:
    return AUGMENTED_CONDITION.curry(condition, puzzle_hash)


def create_augmented_cond_solution(inner_puzzle: Program, inner_solution: Program) -> Any:
    return Program.to([inner_puzzle, inner_solution])


def create_p2_puzzle_hash_puzzle(puzzle_hash: bytes32) -> Any:
    return P2_CURRIED_PUZZLE_HASH.curry(puzzle_hash)


def create_p2_puzzle_hash_solution(inner_puzzle: Program, inner_solution: Program) -> Any:
    return Program.to([inner_puzzle, inner_solution])


def create_clawback_merkle_tree(
    timelock: uint64, sender_ph: bytes32, recipient_ph: bytes32
) -> Tuple[bytes32, Dict[bytes32, Tuple[int, List[bytes32]]]]:
    timelock_condition = [80, timelock]
    augmented_cond_puz = create_augmented_cond_puzzle(timelock_condition, recipient_ph)
    p2_puzzle_hash_puz = create_p2_puzzle_hash_puzzle(sender_ph)
    merkle_tree = build_merkle_tree([augmented_cond_puz.get_tree_hash(), p2_puzzle_hash_puz.get_tree_hash()])
    return merkle_tree


def create_merkle_proof(
    merkle_tree: Tuple[bytes32, Dict[bytes32, Tuple[int, List[bytes32]]]], puzzle_hash: bytes32
) -> Any:
    return Program.to(merkle_tree[1][puzzle_hash])


def create_merkle_puzzle(timelock: uint64, sender_ph: bytes32, recipient_ph: bytes32) -> Program:
    merkle_tree = create_clawback_merkle_tree(timelock, sender_ph, recipient_ph)
    return P2_1_OF_N.curry(merkle_tree[0])


def create_merkle_solution(
    timelock: uint64,
    sender_ph: bytes32,
    recipient_ph: bytes32,
    inner_puzzle: Program,
    inner_solution: Program,
) -> Any:
    merkle_tree = create_clawback_merkle_tree(timelock, sender_ph, recipient_ph)
    if inner_puzzle.get_tree_hash() == sender_ph:
        cb_inner_puz = create_p2_puzzle_hash_puzzle(sender_ph)
        merkle_proof = create_merkle_proof(merkle_tree, cb_inner_puz.get_tree_hash())
        cb_inner_solution = create_p2_puzzle_hash_solution(inner_puzzle, inner_solution)
    elif inner_puzzle.get_tree_hash() == recipient_ph:
        condition = [80, timelock]
        cb_inner_puz = create_augmented_cond_puzzle(condition, recipient_ph)
        merkle_proof = create_merkle_proof(merkle_tree, cb_inner_puz.get_tree_hash())
        cb_inner_solution = create_augmented_cond_solution(inner_puzzle, inner_solution)
    else:
        raise ValueError("Invalid Clawback inner puzzle.")
    return Program.to([merkle_proof, cb_inner_puz, cb_inner_solution])


def match_clawback_puzzle(
    inner_puzzle: Program, inner_solution: Program, max_cost: int
) -> Optional[Tuple[uint64, bytes32, bytes32]]:
    # Check if the inner puzzle is a P2 puzzle
    if MOD != uncurry_puzzle(inner_puzzle).mod:
        return None
    # Fetch Remark condition
    error, conditions, cost = conditions_for_solution(
        inner_puzzle,
        inner_solution,
        max_cost,
    )
    if conditions is not None:
        for condition in conditions:
            if (
                condition.opcode == ConditionOpcode.REMARK
                and len(condition.vars) == 4
                and condition.vars[0] == bytes(PuzzleDecoratorType.CLAWBACK.name, "utf-8")
            ):
                return (
                    uint64(int.from_bytes(condition.vars[1], "big")),
                    bytes32.from_bytes(condition.vars[2]),
                    bytes32.from_bytes(condition.vars[3]),
                )
    return None


def generate_clawback_spend_bundle(
    coin: Coin, metadata: Dict[str, Any], inner_puzzle: Program, inner_solution: Program
) -> CoinSpend:
    time_lock: uint64 = uint64(metadata["time_lock"])
    sender_puzhash: bytes32 = bytes32.fromhex(metadata["sender_puzhash"])
    recipient_puzhash: bytes32 = bytes32.fromhex(metadata["recipient_puzhash"])
    puzzle: Program = create_merkle_puzzle(time_lock, sender_puzhash, recipient_puzhash)
    if puzzle.get_tree_hash() != coin.puzzle_hash:
        raise ValueError(
            f"Cannot spend merkle coin {coin.name()}, "
            f"recreate puzzle hash {puzzle.get_tree_hash().hex()}, actual puzzle hash {coin.puzzle_hash.hex()}"
        )

    solution: Program = create_merkle_solution(
        time_lock, sender_puzhash, recipient_puzhash, inner_puzzle, inner_solution
    )
    return CoinSpend(coin, puzzle, solution)
