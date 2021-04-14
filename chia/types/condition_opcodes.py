import enum
from typing import Any


# See chia/wallet/puzzles/condition_codes.clvm
class ConditionOpcode(bytes, enum.Enum):
    # UNKNOWN is ascii "0"
    UNKNOWN = bytes([48])

    # AGG_SIG is ascii "1"

    # the conditions below require bls12-381 signatures

    AGG_SIG = bytes([49])
    AGG_SIG_ME = bytes([50])

    # the conditions below reserve coin amounts and have to be accounted for in output totals

    CREATE_COIN = bytes([51])
    RESERVE_FEE = bytes([52])

    # the conditions below deal with announcements, for inter-coin communication

    CREATE_COIN_ANNOUNCEMENT = bytes([60])
    ASSERT_COIN_ANNOUNCEMENT = bytes([61])
    CREATE_PUZZLE_ANNOUNCEMENT = bytes([62])
    ASSERT_PUZZLE_ANNOUNCEMENT = bytes([63])

    # the conditions below let coins inquire about themselves

    ASSERT_MY_COIN_ID = bytes([70])
    ASSERT_MY_PARENT_ID = bytes([71])
    ASSERT_MY_PUZZLEHASH = bytes([72])
    ASSERT_MY_AMOUNT = bytes([73])

    # the conditions below ensure that we're "far enough" in the future

    # wall-clock time
    ASSERT_SECONDS_AGE_EXCEEDS = bytes([80])
    ASSERT_SECONDS_NOW_EXCEEDS = bytes([81])

    # block index
    ASSERT_HEIGHT_AGE_EXCEEDS = bytes([82])
    ASSERT_HEIGHT_NOW_EXCEEDS = bytes([83])

    def __bytes__(self) -> bytes:
        return bytes(self.value)

    @classmethod
    def from_bytes(cls: Any, blob: bytes) -> Any:
        assert len(blob) == 1
        return cls(blob)
