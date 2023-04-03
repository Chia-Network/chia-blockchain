from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, List


class Err(Enum):
    # temporary errors. Don't blacklist
    DOES_NOT_EXTEND = -1
    BAD_HEADER_SIGNATURE = -2
    MISSING_FROM_STORAGE = -3
    INVALID_PROTOCOL_MESSAGE = -4  # We WILL ban for a protocol violation.
    SELF_CONNECTION = -5
    INVALID_HANDSHAKE = -6
    INVALID_ACK = -7
    INCOMPATIBLE_PROTOCOL_VERSION = -8
    DUPLICATE_CONNECTION = -9
    BLOCK_NOT_IN_BLOCKCHAIN = -10
    NO_PROOF_OF_SPACE_FOUND = -11
    PEERS_DONT_HAVE_BLOCK = -12
    MAX_INBOUND_CONNECTIONS_REACHED = -13

    UNKNOWN = 1

    # permanent errors. Block is un-salvageable garbage.
    INVALID_BLOCK_SOLUTION = 2
    INVALID_COIN_SOLUTION = 3
    DUPLICATE_OUTPUT = 4
    DOUBLE_SPEND = 5
    UNKNOWN_UNSPENT = 6
    BAD_AGGREGATE_SIGNATURE = 7
    WRONG_PUZZLE_HASH = 8
    BAD_FARMER_COIN_AMOUNT = 9
    INVALID_CONDITION = 10
    ASSERT_MY_COIN_ID_FAILED = 11
    ASSERT_ANNOUNCE_CONSUMED_FAILED = 12
    ASSERT_HEIGHT_RELATIVE_FAILED = 13
    ASSERT_HEIGHT_ABSOLUTE_FAILED = 14
    ASSERT_SECONDS_ABSOLUTE_FAILED = 15
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

    INVALID_POSPACE_HASH = 26
    INVALID_COINBASE_SIGNATURE = 27
    INVALID_PLOT_SIGNATURE = 28
    TIMESTAMP_TOO_FAR_IN_PAST = 29
    TIMESTAMP_TOO_FAR_IN_FUTURE = 30
    INVALID_TRANSACTIONS_FILTER_HASH = 31
    INVALID_POSPACE_CHALLENGE = 32
    INVALID_POSPACE = 33
    INVALID_HEIGHT = 34
    INVALID_COINBASE_AMOUNT = 35
    INVALID_MERKLE_ROOT = 36
    INVALID_BLOCK_FEE_AMOUNT = 37
    INVALID_WEIGHT = 38
    INVALID_TOTAL_ITERS = 39
    BLOCK_IS_NOT_FINISHED = 40
    INVALID_NUM_ITERATIONS = 41
    INVALID_POT = 42
    INVALID_POT_CHALLENGE = 43
    INVALID_TRANSACTIONS_GENERATOR_HASH = 44
    INVALID_POOL_TARGET = 45

    INVALID_COINBASE_PARENT = 46
    INVALID_FEES_COIN_PARENT = 47
    RESERVE_FEE_CONDITION_FAILED = 48

    NOT_BLOCK_BUT_HAS_DATA = 49
    IS_TRANSACTION_BLOCK_BUT_NO_DATA = 50
    INVALID_PREV_BLOCK_HASH = 51
    INVALID_TRANSACTIONS_INFO_HASH = 52
    INVALID_FOLIAGE_BLOCK_HASH = 53
    INVALID_REWARD_COINS = 54
    INVALID_BLOCK_COST = 55
    NO_END_OF_SLOT_INFO = 56
    INVALID_PREV_CHALLENGE_SLOT_HASH = 57
    INVALID_SUB_EPOCH_SUMMARY_HASH = 58
    NO_SUB_EPOCH_SUMMARY_HASH = 59
    SHOULD_NOT_MAKE_CHALLENGE_BLOCK = 60
    SHOULD_MAKE_CHALLENGE_BLOCK = 61
    INVALID_CHALLENGE_CHAIN_DATA = 62
    INVALID_CC_EOS_VDF = 65
    INVALID_RC_EOS_VDF = 66
    INVALID_CHALLENGE_SLOT_HASH_RC = 67
    INVALID_PRIOR_POINT_RC = 68
    INVALID_DEFICIT = 69
    INVALID_SUB_EPOCH_SUMMARY = 70
    INVALID_PREV_SUB_EPOCH_SUMMARY_HASH = 71
    INVALID_REWARD_CHAIN_HASH = 72
    INVALID_SUB_EPOCH_OVERFLOW = 73
    INVALID_NEW_DIFFICULTY = 74
    INVALID_NEW_SUB_SLOT_ITERS = 75
    INVALID_CC_SP_VDF = 76
    INVALID_RC_SP_VDF = 77
    INVALID_CC_SIGNATURE = 78
    INVALID_RC_SIGNATURE = 79
    CANNOT_MAKE_CC_BLOCK = 80
    INVALID_RC_SP_PREV_IP = 81
    INVALID_RC_IP_PREV_IP = 82
    INVALID_IS_TRANSACTION_BLOCK = 83
    INVALID_URSB_HASH = 84
    OLD_POOL_TARGET = 85
    INVALID_POOL_SIGNATURE = 86
    INVALID_FOLIAGE_BLOCK_PRESENCE = 87
    INVALID_CC_IP_VDF = 88
    INVALID_RC_IP_VDF = 89
    IP_SHOULD_BE_NONE = 90
    INVALID_REWARD_BLOCK_HASH = 91
    INVALID_MADE_NON_OVERFLOW_INFUSIONS = 92
    NO_OVERFLOWS_IN_FIRST_SUB_SLOT_NEW_EPOCH = 93

    MEMPOOL_NOT_INITIALIZED = 94
    SHOULD_NOT_HAVE_ICC = 95
    SHOULD_HAVE_ICC = 96
    INVALID_ICC_VDF = 97
    INVALID_ICC_HASH_CC = 98
    INVALID_ICC_HASH_RC = 99
    INVALID_ICC_EOS_VDF = 100
    INVALID_SP_INDEX = 101
    TOO_MANY_BLOCKS = 102
    INVALID_CC_CHALLENGE = 103
    INVALID_PREFARM = 104
    ASSERT_SECONDS_RELATIVE_FAILED = 105
    BAD_COINBASE_SIGNATURE = 106

    # INITIAL_TRANSACTION_FREEZE = 107      # removed
    NO_TRANSACTIONS_WHILE_SYNCING = 108
    ALREADY_INCLUDING_TRANSACTION = 109
    INCOMPATIBLE_NETWORK_ID = 110
    PRE_SOFT_FORK_MAX_GENERATOR_SIZE = 111  # Size in bytes
    INVALID_REQUIRED_ITERS = 112
    TOO_MANY_GENERATOR_REFS = 113  # Number of uint32 entries in the List

    ASSERT_MY_PARENT_ID_FAILED = 114
    ASSERT_MY_PUZZLEHASH_FAILED = 115
    ASSERT_MY_AMOUNT_FAILED = 116
    GENERATOR_RUNTIME_ERROR = 117

    INVALID_COST_RESULT = 118
    INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT = 119
    FUTURE_GENERATOR_REFS = 120  # All refs must be to blocks in the past
    GENERATOR_REF_HAS_NO_GENERATOR = 121
    DOUBLE_SPEND_IN_FORK = 122

    INVALID_FEE_TOO_CLOSE_TO_ZERO = 123
    COIN_AMOUNT_NEGATIVE = 124
    INTERNAL_PROTOCOL_ERROR = 125
    INVALID_SPEND_BUNDLE = 126
    FAILED_GETTING_GENERATOR_MULTIPROCESSING = 127

    ASSERT_BEFORE_SECONDS_ABSOLUTE_FAILED = 128
    ASSERT_BEFORE_SECONDS_RELATIVE_FAILED = 129
    ASSERT_BEFORE_HEIGHT_ABSOLUTE_FAILED = 130
    ASSERT_BEFORE_HEIGHT_RELATIVE_FAILED = 131
    ASSERT_CONCURRENT_SPEND_FAILED = 132
    ASSERT_CONCURRENT_PUZZLE_FAILED = 133

    IMPOSSIBLE_SECONDS_RELATIVE_CONSTRAINTS = 134
    IMPOSSIBLE_SECONDS_ABSOLUTE_CONSTRAINTS = 135
    IMPOSSIBLE_HEIGHT_RELATIVE_CONSTRAINTS = 136
    IMPOSSIBLE_HEIGHT_ABSOLUTE_CONSTRAINTS = 137

    ASSERT_MY_BIRTH_SECONDS_FAILED = 138
    ASSERT_MY_BIRTH_HEIGHT_FAILED = 139

    ASSERT_EPHEMERAL_FAILED = 140
    EPHEMERAL_RELATIVE_CONDITION = 141


class ValidationError(Exception):
    def __init__(self, code: Err, error_msg: str = ""):
        super().__init__(f"Error code: {code.name} {error_msg}")
        self.code = code
        self.error_msg = error_msg


class ConsensusError(Exception):
    def __init__(self, code: Err, errors: List[Any] = []):
        super().__init__(f"Error code: {code.name} {errors}")
        self.errors = errors


class ProtocolError(Exception):
    def __init__(self, code: Err, errors: List[Any] = []):
        super().__init__(f"Error code: {code.name} {errors}")
        self.code = code
        self.errors = errors


##
#  Keychain errors
##


class KeychainException(Exception):
    pass


class KeychainKeyDataMismatch(KeychainException):
    def __init__(self, data_type: str):
        super().__init__(f"KeyData mismatch for: {data_type}")


class KeychainIsLocked(KeychainException):
    pass


class KeychainSecretsMissing(KeychainException):
    pass


class KeychainCurrentPassphraseIsInvalid(KeychainException):
    def __init__(self) -> None:
        super().__init__("Invalid current passphrase")


class KeychainMaxUnlockAttempts(KeychainException):
    def __init__(self) -> None:
        super().__init__("maximum passphrase attempts reached")


class KeychainNotSet(KeychainException):
    pass


class KeychainIsEmpty(KeychainException):
    pass


class KeychainKeyNotFound(KeychainException):
    pass


class KeychainMalformedRequest(KeychainException):
    pass


class KeychainMalformedResponse(KeychainException):
    pass


class KeychainProxyConnectionFailure(KeychainException):
    def __init__(self) -> None:
        super().__init__("Failed to connect to keychain service")


class KeychainLockTimeout(KeychainException):
    pass


class KeychainProxyConnectionTimeout(KeychainException):
    def __init__(self) -> None:
        super().__init__("Could not reconnect to keychain service in 30 seconds.")


class KeychainUserNotFound(KeychainException):
    def __init__(self, service: str, user: str) -> None:
        super().__init__(f"user {user!r} not found for service {service!r}")


class KeychainFingerprintError(KeychainException):
    def __init__(self, fingerprint: int, message: str) -> None:
        self.fingerprint = fingerprint
        super().__init__(f"fingerprint {str(fingerprint)!r} {message}")


class KeychainFingerprintNotFound(KeychainFingerprintError):
    def __init__(self, fingerprint: int) -> None:
        super().__init__(fingerprint, "not found")


class KeychainFingerprintExists(KeychainFingerprintError):
    def __init__(self, fingerprint: int) -> None:
        super().__init__(fingerprint, "already exists")


class KeychainLabelError(KeychainException):
    def __init__(self, label: str, error: str):
        super().__init__(error)
        self.label = label


class KeychainLabelInvalid(KeychainLabelError):
    pass


class KeychainLabelExists(KeychainLabelError):
    def __init__(self, label: str, fingerprint: int) -> None:
        super().__init__(label, f"label {label!r} already exists for fingerprint {str(fingerprint)!r}")
        self.fingerprint = fingerprint


##
#  Miscellaneous errors
##


class InvalidPathError(Exception):
    def __init__(self, path: Path, error_message: str):
        super().__init__(f"{error_message}: {str(path)!r}")
        self.path = path
