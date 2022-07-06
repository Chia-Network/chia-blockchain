from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Union

from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.load_clvm import load_clvm

OWNERSHIP_LAYER_MOD = load_clvm("nft_ownership_layer.clvm")


def match_ownership_layer_puzzle(puzzle: Program) -> Tuple[bool, List[Program]]:
    mod, args = puzzle.uncurry()
    if mod == OWNERSHIP_LAYER_MOD:
        return True, list(args.as_iter())
    return False, []


def puzzle_for_ownership_layer(
    current_owner: Union[Program, bytes], transfer_program: Program, inner_puzzle: Program
) -> Program:
    return OWNERSHIP_LAYER_MOD.curry(OWNERSHIP_LAYER_MOD.get_tree_hash(), current_owner, transfer_program, inner_puzzle)


def solution_for_ownership_layer(inner_solution: Program) -> Program:
    return Program.to([inner_solution])  # type: ignore


@dataclass(frozen=True)
class OwnershipOuterPuzzle:
    _match: Any
    _asset_id: Any
    _construct: Any
    _solve: Any
    _get_inner_puzzle: Any
    _get_inner_solution: Any

    def match(self, puzzle: Program) -> Optional[PuzzleInfo]:
        matched, curried_args = match_ownership_layer_puzzle(puzzle)
        if matched:
            _, current_owner, transfer_program, inner_puzzle = curried_args
            owner_bytes: bytes = current_owner.as_python()
            tp_match: Optional[PuzzleInfo] = self._match(transfer_program)
            constructor_dict = {
                "type": "ownership",
                "owner": "()" if owner_bytes == b"" else "0x" + owner_bytes.hex(),
                "transfer_program": (
                    disassemble(transfer_program) if tp_match is None else tp_match.info  # type: ignore
                ),
            }
            next_constructor = self._match(inner_puzzle)
            if next_constructor is not None:
                constructor_dict["also"] = next_constructor.info
            return PuzzleInfo(constructor_dict)
        else:
            return None

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]:
        return None

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        if constructor.also() is not None:
            inner_puzzle = self._construct(constructor.also(), inner_puzzle)
        transfer_program_info: Union[PuzzleInfo, Program] = constructor["transfer_program"]
        if isinstance(transfer_program_info, Program):
            transfer_program: Program = transfer_program_info
        else:
            transfer_program = self._construct(transfer_program_info, inner_puzzle)
        return puzzle_for_ownership_layer(constructor["owner"], transfer_program, inner_puzzle)

    def get_inner_puzzle(self, constructor: PuzzleInfo, puzzle_reveal: Program) -> Optional[Program]:
        matched, curried_args = match_ownership_layer_puzzle(puzzle_reveal)
        if matched:
            _, _, _, inner_puzzle = curried_args
            if constructor.also() is not None:
                deep_inner_puzzle: Optional[Program] = self._get_inner_puzzle(constructor.also(), inner_puzzle)
                return deep_inner_puzzle
            else:
                return inner_puzzle
        else:
            raise ValueError("This driver is not for the specified puzzle reveal")

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Optional[Program]:
        my_inner_solution: Program = solution.first()
        if constructor.also():
            deep_inner_solution: Optional[Program] = self._get_inner_solution(constructor.also(), my_inner_solution)
            return deep_inner_solution
        else:
            return my_inner_solution

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        if constructor.also() is not None:
            inner_solution = self._solve(constructor.also(), solver, inner_puzzle, inner_solution)
        return solution_for_ownership_layer(inner_solution)
