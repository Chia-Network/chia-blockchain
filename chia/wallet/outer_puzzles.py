from enum import Enum
from typing import Any, Dict, Optional

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.cat_wallet.cat_outer_puzzle import CATOuterPuzzle
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver

"""
This file provides a central location for acquiring drivers for outer puzzles like CATs, NFTs, etc.

A driver for a puzzle must include the following functions:
  - match(self, puzzle: Program) -> Optional[PuzzleInfo]
    - Given a puzzle reveal, return a PuzzleInfo object that can be used to reconstruct it later
  - asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]
    - Given a PuzzleInfo object, generate a 32 byte ID for use in dictionaries, etc.
  - construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program
    - Given a PuzzleInfo object and an innermost puzzle, construct a puzzle reveal for a coin spend
  - solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program
    - Given a PuzzleInfo object, a Solver object, and an innermost puzzle and its solution return a solution for a spend
    - The "Solver" object can contain any dictionary, it's up to the driver to enforce the needed elements of the API
    - Some classes that wish to integrate with a driver may not have access to all of the info it needs so the driver
      needs to raise errors appropriately
"""


class AssetType(Enum):
    CAT = "CAT"


def match_puzzle(puzzle: Program) -> Optional[PuzzleInfo]:
    for driver in driver_lookup.values():
        potential_info: Optional[PuzzleInfo] = driver.match(puzzle)
        if potential_info is not None:
            return potential_info
    return None


def construct_puzzle(constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
    return driver_lookup[AssetType(constructor.type())].construct(constructor, inner_puzzle)  # type: ignore


def solve_puzzle(constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
    return driver_lookup[AssetType(constructor.type())].solve(  # type: ignore
        constructor, solver, inner_puzzle, inner_solution
    )


def create_asset_id(constructor: PuzzleInfo) -> bytes32:
    return driver_lookup[AssetType(constructor.type())].asset_id(constructor)  # type: ignore


function_args = [match_puzzle, construct_puzzle, solve_puzzle, create_asset_id]

driver_lookup: Dict[AssetType, Any] = {
    AssetType.CAT: CATOuterPuzzle(*function_args),
}
