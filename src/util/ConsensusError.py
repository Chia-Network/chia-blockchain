from enum import Enum


class ConsensusError(Exception):
    def __init__(self, code, bad_object):
        self.args = [code, bad_object]
        self.message = str(bad_object)


class Err(Enum):
    # temporary errors. Don't blacklist
    DOES_NOT_EXTEND = -1
    BAD_HEADER_SIGNATURE = -2
    MISSING_FROM_STORAGE = -3

    UNKNOWN = -9999

    # permanent errors. Block is unsalvageable garbage.
    BAD_COINBASE_SIGNATURE = 1
    INVALID_BLOCK_SOLUTION = 2
    INVALID_COIN_SOLUTION = 3
    DUPLICATE_OUTPUT = 4
    DOUBLE_SPEND = 5
    UNKNOWN_UNSPENT = 6
    BAD_AGGREGATE_SIGNATURE = 7
    WRONG_PUZZLE_HASH = 8
    BAD_COINBASE_REWARD = 9
    INVALID_CONDITION = 10
    ASSERT_MY_COIN_ID_FAILED = 11
    ASSERT_COIN_CONSUMED_FAILED = 12
    ASSERT_BLOCK_AGE_EXCEEDS_FAILED = 13
    ASSERT_BLOCK_INDEX_EXCEEDS_FAILED = 14
    ASSERT_TIME_EXCEEDS_FAILED = 15
    COIN_AMOUNT_EXCEEDS_MAXIMUM = 16

    SEXP_ERROR = 17
    INVALID_FEE_LOW_FEE = 18
    MEMPOOL_CONFLICT = 19
    MINTING_COIN = 20
    EXTENDS_UNKNOWN_BLOCK = 21
    COINBASE_NOT_YET_SPENDABLE = 22
    BLOCK_COST_EXCEEDS_MAX = 23
    BAD_ADDITION_ROOT = 24
    BAD_REMOVAL_ROOT = 25
