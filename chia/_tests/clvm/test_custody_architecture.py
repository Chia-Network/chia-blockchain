from __future__ import annotations

from typing import List

import pytest

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.custody.custody_architecture import (
    CustodyHint,
    CustodyWithRestrictions,
    MofN,
    Puzzle,
    Restriction,
    RestrictionHint,
    UnknownCustody,
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
        UnknownCustody(CustodyHint(ANY_HASH, ANY_PROGRAM)),
        MofN(
            1,
            [
                CustodyWithRestrictions(1, [], UnknownCustody(CustodyHint(ANY_HASH, ANY_PROGRAM))),
                CustodyWithRestrictions(
                    2,
                    [
                        UnknownRestriction(RestrictionHint(True, ANY_HASH, ANY_PROGRAM)),
                        UnknownRestriction(RestrictionHint(True, ANY_HASH, ANY_PROGRAM)),
                    ],
                    UnknownCustody(CustodyHint(ANY_HASH, ANY_PROGRAM)),
                ),
            ],
        ),
        MofN(
            2,
            [
                CustodyWithRestrictions(
                    1, [], MofN(1, [CustodyWithRestrictions(3, [], UnknownCustody(CustodyHint(ANY_HASH, ANY_PROGRAM)))])
                ),
                CustodyWithRestrictions(
                    4, [], MofN(1, [CustodyWithRestrictions(5, [], UnknownCustody(CustodyHint(ANY_HASH, ANY_PROGRAM)))])
                ),
            ],
        ),
    ],
)
def test_back_and_forth_hint_parsing(restrictions: List[Restriction], custody: Puzzle) -> None:
    cwr = CustodyWithRestrictions(
        nonce=0,
        restrictions=restrictions,
        custody=custody,
    )

    assert CustodyWithRestrictions.from_memo(cwr.memo()) == cwr
