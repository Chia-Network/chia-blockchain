from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List

import pytest

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.custody.custody_architecture import (
    MofN,
    Puzzle,
    PuzzleHint,
    PuzzleWithRestrictions,
    Restriction,
    RestrictionHint,
    UnknownPuzzle,
    UnknownRestriction,
)

ANY_HASH = bytes32([0] * 32)
ANY_PROGRAM = Program.to(None)


@pytest.mark.parametrize(
    "restrictions",
    [
        [],
        [UnknownRestriction(RestrictionHint(True, ANY_HASH, ANY_PROGRAM))],
        [UnknownRestriction(RestrictionHint(False, ANY_HASH, ANY_PROGRAM))],
        [
            UnknownRestriction(RestrictionHint(True, ANY_HASH, ANY_PROGRAM)),
            UnknownRestriction(RestrictionHint(False, ANY_HASH, ANY_PROGRAM)),
        ],
    ],
)
@pytest.mark.parametrize(
    "custody",
    [
        UnknownPuzzle(PuzzleHint(ANY_HASH, ANY_PROGRAM)),
        MofN(
            1,
            [
                PuzzleWithRestrictions(1, [], UnknownPuzzle(PuzzleHint(ANY_HASH, ANY_PROGRAM))),
                PuzzleWithRestrictions(
                    2,
                    [
                        UnknownRestriction(RestrictionHint(True, ANY_HASH, ANY_PROGRAM)),
                        UnknownRestriction(RestrictionHint(True, ANY_HASH, ANY_PROGRAM)),
                    ],
                    UnknownPuzzle(PuzzleHint(ANY_HASH, ANY_PROGRAM)),
                ),
            ],
        ),
        MofN(
            2,
            [
                PuzzleWithRestrictions(
                    1, [], MofN(1, [PuzzleWithRestrictions(3, [], UnknownPuzzle(PuzzleHint(ANY_HASH, ANY_PROGRAM)))])
                ),
                PuzzleWithRestrictions(
                    4, [], MofN(1, [PuzzleWithRestrictions(5, [], UnknownPuzzle(PuzzleHint(ANY_HASH, ANY_PROGRAM)))])
                ),
            ],
        ),
    ],
)
def test_back_and_forth_hint_parsing(restrictions: List[Restriction], custody: Puzzle) -> None:
    cwr = PuzzleWithRestrictions(
        nonce=0,
        restrictions=restrictions,
        custody=custody,
    )

    assert PuzzleWithRestrictions.from_memo(cwr.memo()) == cwr


def test_unknown_puzzle_behavior() -> None:
    @dataclass(frozen=True)
    class PlaceholderPuzzle:
        @property
        def _morpher_not_validator(self) -> bool:
            raise NotImplementedError()

        def memo(self, nonce: int) -> Program:
            raise NotImplementedError()

        def puzzle(self, nonce: int) -> Program:
            raise NotImplementedError()

        def puzzle_hash(self, nonce: int) -> bytes32:
            raise NotImplementedError()

    BUNCH_OF_ZEROS = bytes32([0] * 32)
    BUNCH_OF_ONES = bytes32([1] * 32)
    BUNCH_OF_TWOS = bytes32([2] * 32)
    BUNCH_OF_THREES = bytes32([3] * 32)

    # First a simple PuzzleWithRestrictions that is really just a Puzzle
    unknown_puzzle_0 = UnknownPuzzle(PuzzleHint(BUNCH_OF_ZEROS, ANY_PROGRAM))
    pwr = PuzzleWithRestrictions(0, [], unknown_puzzle_0)
    assert pwr.unknown_puzzles == {BUNCH_OF_ZEROS: unknown_puzzle_0}
    known_puzzles = {BUNCH_OF_ZEROS: PlaceholderPuzzle()}
    assert pwr.fill_in_unknown_puzzles(known_puzzles) == PuzzleWithRestrictions(0, [], PlaceholderPuzzle())

    # Now we add some restrictions
    unknown_restriction_1 = UnknownRestriction(RestrictionHint(True, BUNCH_OF_ONES, ANY_PROGRAM))
    unknown_restriction_2 = UnknownRestriction(RestrictionHint(False, BUNCH_OF_TWOS, ANY_PROGRAM))
    pwr = replace(pwr, restrictions=[unknown_restriction_1, unknown_restriction_2])
    assert pwr.unknown_puzzles == {
        BUNCH_OF_ZEROS: unknown_puzzle_0,
        BUNCH_OF_ONES: unknown_restriction_1,
        BUNCH_OF_TWOS: unknown_restriction_2,
    }
    known_puzzles = {
        BUNCH_OF_ZEROS: PlaceholderPuzzle(),
        BUNCH_OF_ONES: PlaceholderPuzzle(),
        BUNCH_OF_TWOS: PlaceholderPuzzle(),
    }
    assert pwr.fill_in_unknown_puzzles(known_puzzles) == PuzzleWithRestrictions(
        0, [PlaceholderPuzzle(), PlaceholderPuzzle()], PlaceholderPuzzle()
    )

    # Now we do test an MofN recursion
    unknown_puzzle_3 = UnknownPuzzle(PuzzleHint(BUNCH_OF_THREES, ANY_PROGRAM))
    pwr = replace(
        pwr,
        custody=MofN(
            m=1,
            members=[PuzzleWithRestrictions(0, [], unknown_puzzle_0), PuzzleWithRestrictions(0, [], unknown_puzzle_3)],
        ),
    )
    assert pwr.unknown_puzzles == {
        BUNCH_OF_ZEROS: unknown_puzzle_0,
        BUNCH_OF_ONES: unknown_restriction_1,
        BUNCH_OF_TWOS: unknown_restriction_2,
        BUNCH_OF_THREES: unknown_puzzle_3,
    }
    known_puzzles = {
        BUNCH_OF_ZEROS: PlaceholderPuzzle(),
        BUNCH_OF_ONES: PlaceholderPuzzle(),
        BUNCH_OF_TWOS: PlaceholderPuzzle(),
        BUNCH_OF_THREES: PlaceholderPuzzle(),
    }
    assert pwr.fill_in_unknown_puzzles(known_puzzles) == PuzzleWithRestrictions(
        0,
        [PlaceholderPuzzle(), PlaceholderPuzzle()],
        MofN(
            m=1,
            members=[
                PuzzleWithRestrictions(0, [], PlaceholderPuzzle()),
                PuzzleWithRestrictions(0, [], PlaceholderPuzzle()),
            ],
        ),
    )
