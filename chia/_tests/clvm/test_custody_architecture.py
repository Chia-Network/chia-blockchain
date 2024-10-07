from __future__ import annotations

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
