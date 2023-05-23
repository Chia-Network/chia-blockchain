from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_LAUNCHER_HASH, SINGLETON_MOD_HASH
from chia.wallet.uncurried_puzzle import UncurriedPuzzle

TRANSFER_PROGRAM_MOD = load_clvm_maybe_recompile("nft_ownership_transfer_program_one_way_claim_with_royalties.clsp")


def match_transfer_program_puzzle(puzzle: UncurriedPuzzle) -> Tuple[bool, List[Program]]:
    if puzzle.mod == TRANSFER_PROGRAM_MOD:
        return True, list(puzzle.args.as_iter())
    return False, []


def puzzle_for_transfer_program(launcher_id: bytes32, royalty_puzzle_hash: bytes32, percentage: uint16) -> Program:
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (launcher_id, SINGLETON_LAUNCHER_HASH)))
    return TRANSFER_PROGRAM_MOD.curry(
        singleton_struct,
        royalty_puzzle_hash,
        percentage,
    )


def solution_for_transfer_program(
    conditions: Program,
    current_owner: Optional[bytes32],
    new_did: bytes32,
    new_did_inner_hash: bytes32,
    trade_prices_list: Program,
) -> Program:
    return Program.to([conditions, current_owner, [new_did, trade_prices_list, new_did_inner_hash]])  # type: ignore


@dataclass(frozen=True)
class TransferProgramPuzzle:
    _match: Callable[[UncurriedPuzzle], Optional[PuzzleInfo]]
    _construct: Callable[[PuzzleInfo, Program], Program]
    _solve: Callable[[PuzzleInfo, Solver, Program, Program], Program]
    _get_inner_puzzle: Callable[[PuzzleInfo, UncurriedPuzzle], Optional[Program]]
    _get_inner_solution: Callable[[PuzzleInfo, Program], Optional[Program]]

    def match(self, puzzle: UncurriedPuzzle) -> Optional[PuzzleInfo]:
        matched, curried_args = match_transfer_program_puzzle(puzzle)
        if matched:
            singleton_struct, royalty_puzzle_hash, percentage = curried_args
            constructor_dict = {
                "type": "royalty transfer program",
                "launcher_id": "0x" + singleton_struct.rest().first().as_python().hex(),
                "royalty_address": "0x" + royalty_puzzle_hash.as_python().hex(),
                "royalty_percentage": str(percentage.as_int()),
            }
            return PuzzleInfo(constructor_dict)
        else:
            return None

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]:
        return None

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        return puzzle_for_transfer_program(
            constructor["launcher_id"], constructor["royalty_address"], constructor["royalty_percentage"]
        )

    def get_inner_puzzle(self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle) -> Optional[Program]:
        return None

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Optional[Program]:
        return None

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        return Program.to(None)  # type: ignore
