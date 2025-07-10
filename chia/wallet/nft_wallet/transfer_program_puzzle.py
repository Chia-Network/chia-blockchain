from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16

from chia.types.blockchain_format.program import Program
from chia.wallet.nft_wallet.nft_puzzles import NFT_TRANSFER_PROGRAM_DEFAULT
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_LAUNCHER_HASH, SINGLETON_MOD_HASH
from chia.wallet.uncurried_puzzle import UncurriedPuzzle


def match_transfer_program_puzzle(puzzle: UncurriedPuzzle) -> tuple[bool, list[Program]]:
    if puzzle.mod == NFT_TRANSFER_PROGRAM_DEFAULT:
        return True, list(puzzle.args.as_iter())
    return False, []


def puzzle_for_transfer_program(launcher_id: bytes32, royalty_puzzle_hash: bytes32, percentage: uint16) -> Program:
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (launcher_id, SINGLETON_LAUNCHER_HASH)))
    return NFT_TRANSFER_PROGRAM_DEFAULT.curry(
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
    return Program.to([conditions, current_owner, [new_did, trade_prices_list, new_did_inner_hash]])


@dataclass(frozen=True)
class TransferProgramPuzzle:
    _match: Callable[[UncurriedPuzzle], Optional[PuzzleInfo]]
    _construct: Callable[[PuzzleInfo, Program], Program]
    _solve: Callable[[PuzzleInfo, Solver, Program, Program], Program]
    _get_inner_puzzle: Callable[[PuzzleInfo, UncurriedPuzzle, Optional[Program]], Optional[Program]]
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

    def get_inner_puzzle(
        self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle, solution: Optional[Program] = None
    ) -> Optional[Program]:
        return None

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Optional[Program]:
        return None

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        return Program.to(None)
