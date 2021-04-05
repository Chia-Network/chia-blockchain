import enum
from typing import Any


# See chia/wallet/puzzles/condition_codes.clvm
class ConditionOpcode(bytes, enum.Enum):
    # UNKNOWN is ascii "0"
    UNKNOWN = bytes([48])

    # AGG_SIG is ascii "1"

    # signature opcodes
    AGG_SIG = bytes([49])
    AGG_SIG_ME = bytes([50])

    # creation opcodes
    CREATE_COIN = bytes([51])
    CREATE_ANNOUNCEMENT = bytes([52])

    # assertions: coins & announcements
    ASSERT_ANNOUNCEMENT = bytes([53])
    ASSERT_MY_COIN_ID = bytes([54])

    # wall-clock time
    ASSERT_SECONDS_AGE_EXCEEDS = bytes([55])
    ASSERT_SECONDS_NOW_EXCEEDS = bytes([56])

    # block index
    ASSERT_HEIGHT_AGE_EXCEEDS = bytes([57])
    ASSERT_HEIGHT_NOW_EXCEEDS = bytes([58])

    # fee
    RESERVE_FEE = bytes([59])

    def __bytes__(self) -> bytes:
        return bytes(self.value)

    @classmethod
    def from_bytes(cls: Any, blob: bytes) -> Any:
        assert len(blob) == 1
        return cls(blob)
