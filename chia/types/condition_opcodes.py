from __future__ import annotations

import enum
from typing import Any


# See chia/wallet/puzzles/condition_codes.clib
class ConditionOpcode(bytes, enum.Enum):
    # AGG_SIG is ascii "1"

    # the conditions below require bls12-381 signatures

    AGG_SIG_UNSAFE = bytes([49])
    AGG_SIG_ME = bytes([50])

    # the conditions below reserve coin amounts and have to be accounted for in output totals

    CREATE_COIN = bytes([51])
    RESERVE_FEE = bytes([52])

    # the conditions below deal with announcements, for inter-coin communication

    CREATE_COIN_ANNOUNCEMENT = bytes([60])
    ASSERT_COIN_ANNOUNCEMENT = bytes([61])
    CREATE_PUZZLE_ANNOUNCEMENT = bytes([62])
    ASSERT_PUZZLE_ANNOUNCEMENT = bytes([63])
    ASSERT_CONCURRENT_SPEND = bytes([64])
    ASSERT_CONCURRENT_PUZZLE = bytes([65])

    # the conditions below let coins inquire about themselves

    ASSERT_MY_COIN_ID = bytes([70])
    ASSERT_MY_PARENT_ID = bytes([71])
    ASSERT_MY_PUZZLEHASH = bytes([72])
    ASSERT_MY_AMOUNT = bytes([73])
    ASSERT_MY_BIRTH_SECONDS = bytes([74])
    ASSERT_MY_BIRTH_HEIGHT = bytes([75])
    ASSERT_EPHEMERAL = bytes([76])

    # the conditions below ensure that we're "far enough" in the future

    # wall-clock time
    ASSERT_SECONDS_RELATIVE = bytes([80])
    ASSERT_SECONDS_ABSOLUTE = bytes([81])

    # block index
    ASSERT_HEIGHT_RELATIVE = bytes([82])
    ASSERT_HEIGHT_ABSOLUTE = bytes([83])

    # wall-clock time
    ASSERT_BEFORE_SECONDS_RELATIVE = bytes([84])
    ASSERT_BEFORE_SECONDS_ABSOLUTE = bytes([85])

    # block index
    ASSERT_BEFORE_HEIGHT_RELATIVE = bytes([86])
    ASSERT_BEFORE_HEIGHT_ABSOLUTE = bytes([87])

    # A condition that is always true and always ignore all arguments
    REMARK = bytes([1])

    def __bytes__(self) -> bytes:
        return bytes(self.value)

    @classmethod
    def from_bytes(cls: Any, blob: bytes) -> Any:
        assert len(blob) == 1
        return cls(blob)
