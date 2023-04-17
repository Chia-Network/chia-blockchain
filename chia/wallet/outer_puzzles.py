from __future__ import annotations

from enum import Enum
from typing import Dict, Optional

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.cat_wallet.cat_outer_puzzle import CATOuterPuzzle
from chia.wallet.driver_protocol import DriverProtocol
from chia.wallet.nft_wallet.metadata_outer_puzzle import MetadataOuterPuzzle
from chia.wallet.nft_wallet.ownership_outer_puzzle import OwnershipOuterPuzzle
from chia.wallet.nft_wallet.singleton_outer_puzzle import SingletonOuterPuzzle
from chia.wallet.nft_wallet.transfer_program_puzzle import TransferProgramPuzzle
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.uncurried_puzzle import UncurriedPuzzle

"""
This file provides a central location for acquiring drivers for outer puzzles like CATs, NFTs, etc.

A driver for a puzzle must include the following functions:
  - match(self, puzzle: UncurriedPuzzle) -> Optional[PuzzleInfo]
    - Given a puzzle reveal, return a PuzzleInfo object that can be used to reconstruct it later
  - get_inner_puzzle(self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle) -> Optional[Program]:
    - Given a PuzzleInfo object and a puzzle reveal, pull out this outer puzzle's inner puzzle
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
    SINGLETON = "singleton"
    METADATA = "metadata"
    OWNERSHIP = "ownership"
    ROYALTY_TRANSFER_PROGRAM = "royalty transfer program"


def match_puzzle(puzzle: UncurriedPuzzle) -> Optional[PuzzleInfo]:
    for driver in driver_lookup.values():
        potential_info: Optional[PuzzleInfo] = driver.match(puzzle)
        if potential_info is not None:
            return potential_info
    return None


def construct_puzzle(constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
    return driver_lookup[AssetType(constructor.type())].construct(constructor, inner_puzzle)


def solve_puzzle(constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
    return driver_lookup[AssetType(constructor.type())].solve(constructor, solver, inner_puzzle, inner_solution)


def get_inner_puzzle(constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle) -> Optional[Program]:
    return driver_lookup[AssetType(constructor.type())].get_inner_puzzle(constructor, puzzle_reveal)


def get_inner_solution(constructor: PuzzleInfo, solution: Program) -> Optional[Program]:
    return driver_lookup[AssetType(constructor.type())].get_inner_solution(constructor, solution)


def create_asset_id(constructor: PuzzleInfo) -> Optional[bytes32]:
    return driver_lookup[AssetType(constructor.type())].asset_id(constructor)


function_args = (match_puzzle, construct_puzzle, solve_puzzle, get_inner_puzzle, get_inner_solution)

driver_lookup: Dict[AssetType, DriverProtocol] = {
    AssetType.CAT: CATOuterPuzzle(*function_args),
    AssetType.SINGLETON: SingletonOuterPuzzle(*function_args),
    AssetType.METADATA: MetadataOuterPuzzle(*function_args),
    AssetType.OWNERSHIP: OwnershipOuterPuzzle(*function_args),
    AssetType.ROYALTY_TRANSFER_PROGRAM: TransferProgramPuzzle(*function_args),
}
