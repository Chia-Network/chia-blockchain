import enum


class ConditionOpcode(bytes, enum.Enum):
    UNKNOWN = bytes([49])
    AGG_SIG = bytes([50])
    CREATE_COIN = bytes([51])
    ASSERT_COIN_CONSUMED = bytes([52])
    ASSERT_MY_COIN_ID = bytes([53])
    ASSERT_TIME_EXCEEDS = bytes([54])
    ASSERT_BLOCK_INDEX_EXCEEDS = bytes([55])
    ASSERT_BLOCK_AGE_EXCEEDS = bytes([56])
    AGG_SIG_ME = bytes([57])
    ASSERT_FEE = bytes([58])
