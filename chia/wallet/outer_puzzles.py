from enum import Enum
from typing import Any, Dict, Optional

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.cat_wallet.cat_outer_puzzle import CATOuterPuzzle
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver


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
