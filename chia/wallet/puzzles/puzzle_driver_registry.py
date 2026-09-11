from __future__ import annotations

from dataclasses import dataclass

from chia.wallet.puzzles import puzzle_drivers
from chia.wallet.puzzles.custody import custody_architecture, member_puzzles, restriction_utilities, restrictions

"""
This file may have more utility in the future but for right now it acts as a substitute for putting:
```
if TYPE_CHECKING:
    _protocol_check: ClassVar[Puzzle/Solution] = cast("Something", None)
```
into every driver class
"""


@dataclass(frozen=True, kw_only=True)
class PuzzleDriverSet:
    name: str
    puzzle: type[puzzle_drivers.Puzzle]
    solution: type[puzzle_drivers.Solution]


DRIVER_REGISTRY = [
    PuzzleDriverSet(name="unknown", puzzle=puzzle_drivers.UnknownPuzzle, solution=puzzle_drivers.UnknownSolution),
    PuzzleDriverSet(name="acs", puzzle=puzzle_drivers.ACSPuzzle, solution=puzzle_drivers.ACSSolution),
    PuzzleDriverSet(name="nil", puzzle=puzzle_drivers.NilPuzzle, solution=puzzle_drivers.NilSolution),
    PuzzleDriverSet(name="p2_conditions", puzzle=puzzle_drivers.P2Conditions, solution=puzzle_drivers.NilSolution),
    PuzzleDriverSet(
        name="unknown_member",
        puzzle=custody_architecture.UnknownMember,
        solution=puzzle_drivers.UnknownSolution,
    ),
    PuzzleDriverSet(
        name="unknown_restriction",
        puzzle=custody_architecture.UnknownRestriction,
        solution=puzzle_drivers.UnknownSolution,
    ),
    PuzzleDriverSet(
        name="m_of_n",
        puzzle=custody_architecture.MofN,
        solution=custody_architecture.MofNSolution,
    ),
    PuzzleDriverSet(
        name="puzzle_with_restrictions",
        puzzle=custody_architecture.PuzzleWithRestrictions,
        solution=custody_architecture.PuzzleWithRestrictionsSolution,
    ),
    PuzzleDriverSet(
        name="bls_with_taproot_member",
        puzzle=member_puzzles.BLSWithTaprootMember,
        solution=member_puzzles.BLSWithTaprootMemberSolution,
    ),
    PuzzleDriverSet(
        name="singleton_member",
        puzzle=member_puzzles.SingletonMember,
        solution=member_puzzles.SingletonMemberSolution,
    ),
    PuzzleDriverSet(
        name="fixed_puzzle_member",
        puzzle=member_puzzles.FixedPuzzleMember,
        solution=puzzle_drivers.NilSolution,
    ),
    PuzzleDriverSet(
        name="heightlock",
        puzzle=restrictions.Heightlock,
        solution=puzzle_drivers.NilSolution,
    ),
    PuzzleDriverSet(
        name="fixed_create_coin_destinations",
        puzzle=restrictions.FixedCreateCoinDestinations,
        solution=puzzle_drivers.NilSolution,
    ),
    PuzzleDriverSet(
        name="send_message_banned",
        puzzle=restrictions.SendMessageBanned,
        solution=puzzle_drivers.NilSolution,
    ),
    PuzzleDriverSet(
        name="validator_stack_restriction",
        puzzle=restriction_utilities.ValidatorStackRestriction,
        solution=restriction_utilities.ValidatorStackRestrictionSolution,
    ),
]
