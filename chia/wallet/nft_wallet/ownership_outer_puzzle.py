from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple, Union

from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle

OWNERSHIP_LAYER_MOD = load_clvm_maybe_recompile(
    "nft_ownership_layer.clsp", package_or_requirement="chia.wallet.nft_wallet.puzzles"
)


def match_ownership_layer_puzzle(puzzle: UncurriedPuzzle) -> Tuple[bool, List[Program]]:
    if puzzle.mod == OWNERSHIP_LAYER_MOD:
        return True, list(puzzle.args.as_iter())
    return False, []


def puzzle_for_ownership_layer(
    current_owner: Union[Program, bytes], transfer_program: Program, inner_puzzle: Program
) -> Program:
    return OWNERSHIP_LAYER_MOD.curry(OWNERSHIP_LAYER_MOD.get_tree_hash(), current_owner, transfer_program, inner_puzzle)


def solution_for_ownership_layer(inner_solution: Program) -> Program:
    return Program.to([inner_solution])


@dataclass(frozen=True)
class OwnershipOuterPuzzle:
    _match: Callable[[UncurriedPuzzle], Optional[PuzzleInfo]]
    _construct: Callable[[PuzzleInfo, Program], Program]
    _solve: Callable[[PuzzleInfo, Solver, Program, Program], Program]
    _get_inner_puzzle: Callable[[PuzzleInfo, UncurriedPuzzle], Optional[Program]]
    _get_inner_solution: Callable[[PuzzleInfo, Program], Optional[Program]]

    def match(self, puzzle: UncurriedPuzzle) -> Optional[PuzzleInfo]:
        matched, curried_args = match_ownership_layer_puzzle(puzzle)
        if matched:
            _, current_owner, transfer_program, inner_puzzle = curried_args
            owner_bytes: bytes = current_owner.as_python()
            tp_match: Optional[PuzzleInfo] = self._match(uncurry_puzzle(transfer_program))
            constructor_dict = {
                "type": "ownership",
                "owner": "()" if owner_bytes == b"" else "0x" + owner_bytes.hex(),
                "transfer_program": (disassemble(transfer_program) if tp_match is None else tp_match.info),
            }
            next_constructor = self._match(uncurry_puzzle(inner_puzzle))
            if next_constructor is not None:
                constructor_dict["also"] = next_constructor.info
            return PuzzleInfo(constructor_dict)
        else:
            return None

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]:
        return None

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        also = constructor.also()
        if also is not None:
            inner_puzzle = self._construct(also, inner_puzzle)
        transfer_program_info: Union[PuzzleInfo, Program] = constructor["transfer_program"]
        if isinstance(transfer_program_info, Program):
            transfer_program: Program = transfer_program_info
        else:
            transfer_program = self._construct(transfer_program_info, inner_puzzle)
        return puzzle_for_ownership_layer(constructor["owner"], transfer_program, inner_puzzle)

    def get_inner_puzzle(self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle) -> Optional[Program]:
        matched, curried_args = match_ownership_layer_puzzle(puzzle_reveal)
        if matched:
            _, _, _, inner_puzzle = curried_args
            also = constructor.also()
            if also is not None:
                deep_inner_puzzle: Optional[Program] = self._get_inner_puzzle(also, uncurry_puzzle(inner_puzzle))
                return deep_inner_puzzle
            else:
                return inner_puzzle
        else:
            raise ValueError("This driver is not for the specified puzzle reveal")

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Optional[Program]:
        my_inner_solution: Program = solution.first()
        also = constructor.also()
        if also:
            deep_inner_solution: Optional[Program] = self._get_inner_solution(also, my_inner_solution)
            return deep_inner_solution
        else:
            return my_inner_solution

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        also = constructor.also()
        if also is not None:
            inner_solution = self._solve(also, solver, inner_puzzle, inner_solution)
        return solution_for_ownership_layer(inner_solution)
