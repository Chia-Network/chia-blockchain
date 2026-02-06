"""
Structured RPC errors for the Chia RPC layer.

Exports:
  - RpcError: exception class carrying error code, message, structured message, and data.
  - RpcErrorCodes: enum of all known error codes.
  - StructuredError: TypedDict describing the shape of the structuredError response object.
  - structured_error_from_exception: builds (legacy error string, StructuredError dict) from any exception.
  - rpc_error_to_response: builds the full error response dict for returning (not raising) errors.

All RPC error responses include the existing ``error`` string field (unchanged for
backwards compatibility) plus a ``structuredError`` object with code, originalError,
structuredMessage, and data.

Keys and values in ``data`` must be JSON-serializable so that response encoding
does not fail.

Both HTTP handlers (rpc/util.py) and WebSocket handlers (rpc_server.py) include
``structuredError`` in the response.  HTTP handlers additionally include a
``traceback`` field; WebSocket handlers do not.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict


class StructuredError(TypedDict):
    """Shape of the structuredError object in RPC error responses."""

    code: str
    originalError: str
    structuredMessage: str
    data: dict[str, Any]


class RpcErrorCodes(str, Enum):
    """All RPC error codes. Use these instead of raw strings when raising RpcError."""

    ADDITIONS_LIST_REQUIRED = "ADDITIONS_LIST_REQUIRED"
    ADDRESS_INVALID_LENGTH = "ADDRESS_INVALID_LENGTH"
    ADD_PLOT_DIRECTORY_FAILED = "ADD_PLOT_DIRECTORY_FAILED"
    AFTER_REQUIRED = "AFTER_REQUIRED"
    ALREADY_FARMING_TO_POOL = "ALREADY_FARMING_TO_POOL"
    BATCH_UPDATE_FAILED = "BATCH_UPDATE_FAILED"
    BLOCK_DOES_NOT_EXIST = "BLOCK_DOES_NOT_EXIST"
    BLOCK_HASH_NOT_FOUND = "BLOCK_HASH_NOT_FOUND"
    BLOCK_HEIGHT_NOT_FOUND = "BLOCK_HEIGHT_NOT_FOUND"
    BLOCK_IN_FORK = "BLOCK_IN_FORK"
    BLOCK_NOT_FOUND = "BLOCK_NOT_FOUND"
    CANNOT_COMBINE_NFT = "CANNOT_COMBINE_NFT"
    CANNOT_FIND_CHILD_COIN = "CANNOT_FIND_CHILD_COIN"
    CANNOT_FIND_KEYS = "CANNOT_FIND_KEYS"
    CANNOT_FIND_KEYS_AND_VALUES = "CANNOT_FIND_KEYS_AND_VALUES"
    CANNOT_PUSH_IF_FALSE = "CANNOT_PUSH_IF_FALSE"
    CANNOT_PUSH_INCOMPLETE_SPEND = "CANNOT_PUSH_INCOMPLETE_SPEND"
    CANNOT_SPLIT_NFT = "CANNOT_SPLIT_NFT"
    CHANGELIST_REQUIRED = "CHANGELIST_REQUIRED"
    COINS_LIMIT_EXCEEDED = "COINS_LIMIT_EXCEEDED"
    COIN_AMOUNT_EXCEEDS_MAX = "COIN_AMOUNT_EXCEEDS_MAX"
    COIN_AMOUNT_LESS_THAN_SPLIT = "COIN_AMOUNT_LESS_THAN_SPLIT"
    COIN_IDS_NOT_FOUND = "COIN_IDS_NOT_FOUND"
    COIN_NOT_DID = "COIN_NOT_DID"
    COIN_NOT_FOUND = "COIN_NOT_FOUND"
    COIN_NOT_NFT = "COIN_NOT_NFT"
    COIN_RECORDS_LIMIT_EXCEEDED = "COIN_RECORDS_LIMIT_EXCEEDED"
    COIN_RECORD_NOT_FOUND = "COIN_RECORD_NOT_FOUND"
    CONDITIONS_REQUIRE_FEE_SPEND = "CONDITIONS_REQUIRE_FEE_SPEND"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    CONNECTION_NOT_FOUND = "CONNECTION_NOT_FOUND"
    DATA_LAYER_NOT_CREATED = "DATA_LAYER_NOT_CREATED"
    DELETE_PLOT_FAILED = "DELETE_PLOT_FAILED"
    DERIVATION_INDEX_TOO_LOW = "DERIVATION_INDEX_TOO_LOW"
    DID_NOT_FOUND = "DID_NOT_FOUND"
    DID_NOT_IN_WALLET = "DID_NOT_IN_WALLET"
    EOS_NOT_IN_CACHE = "EOS_NOT_IN_CACHE"
    FAILED_TO_GET_KEYS = "FAILED_TO_GET_KEYS"
    FAILED_TO_START = "FAILED_TO_START"
    FILTER_ITEMS_EXCEEDED = "FILTER_ITEMS_EXCEEDED"
    FINGERPRINT_NOT_FOUND = "FINGERPRINT_NOT_FOUND"
    GLOBAL_CONNECTIONS_NOT_SET = "GLOBAL_CONNECTIONS_NOT_SET"
    HEADER_HASH_NOT_IN_REQUEST = "HEADER_HASH_NOT_IN_REQUEST"
    HEIGHT_NOT_IN_BLOCKCHAIN = "HEIGHT_NOT_IN_BLOCKCHAIN"
    HINT_NOT_IN_REQUEST = "HINT_NOT_IN_REQUEST"
    INVALID_BLOCK_OR_GENERATOR = "INVALID_BLOCK_OR_GENERATOR"
    INVALID_COIN_ID_FORMAT = "INVALID_COIN_ID_FORMAT"
    INVALID_HEIGHT_FOR_COIN = "INVALID_HEIGHT_FOR_COIN"
    INVALID_NETWORK_SPACE_REQUEST = "INVALID_NETWORK_SPACE_REQUEST"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_SIGNING_MODE = "INVALID_SIGNING_MODE"
    INVALID_SORT_KEY = "INVALID_SORT_KEY"
    LAUNCHER_COIN_NOT_FOUND = "LAUNCHER_COIN_NOT_FOUND"
    LAUNCH_COIN_NOT_FOUND = "LAUNCH_COIN_NOT_FOUND"
    LOGIN_LINK_FAILED = "LOGIN_LINK_FAILED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    METADATA_UPDATE_FAILED = "METADATA_UPDATE_FAILED"
    MISSING_STORE_ID = "MISSING_STORE_ID"
    MNEMONIC_WORD_INCORRECT = "MNEMONIC_WORD_INCORRECT"
    MORE_COINS_THAN_DESIRED = "MORE_COINS_THAN_DESIRED"
    NAMES_NOT_IN_REQUEST = "NAMES_NOT_IN_REQUEST"
    NAME_NOT_IN_REQUEST = "NAME_NOT_IN_REQUEST"
    NEED_TWO_COINS_TO_COMBINE = "NEED_TWO_COINS_TO_COMBINE"
    NEED_UPGRADED_SINGLETON = "NEED_UPGRADED_SINGLETON"
    NEWER_BLOCK_NOT_FOUND = "NEWER_BLOCK_NOT_FOUND"
    NEW_AND_OLD_MUST_DIFFER = "NEW_AND_OLD_MUST_DIFFER"
    NFT_CHUNK_LIMIT_SET = "NFT_CHUNK_LIMIT_SET"
    NFT_CHUNK_LIMIT_TRANSFER = "NFT_CHUNK_LIMIT_TRANSFER"
    NFT_MINT_PUSH_UNAVAILABLE = "NFT_MINT_PUSH_UNAVAILABLE"
    NFT_NOT_FOUND = "NFT_NOT_FOUND"
    NFT_NO_DID_SUPPORT = "NFT_NO_DID_SUPPORT"
    NFT_WALLET_DID_NOT_FOUND = "NFT_WALLET_DID_NOT_FOUND"
    NOT_A_SINGLETON = "NOT_A_SINGLETON"
    NO_BLOCKS_IN_CHAIN = "NO_BLOCKS_IN_CHAIN"
    NO_BLOCKS_TO_REVERT = "NO_BLOCKS_TO_REVERT"
    NO_COIN_NAME_IN_REQUEST = "NO_COIN_NAME_IN_REQUEST"
    NO_DERIVATION_RECORD = "NO_DERIVATION_RECORD"
    NO_END_IN_REQUEST = "NO_END_IN_REQUEST"
    NO_FULL_NODE_PEERS = "NO_FULL_NODE_PEERS"
    NO_HEADER_HASH_IN_REQUEST = "NO_HEADER_HASH_IN_REQUEST"
    NO_HEIGHT_IN_REQUEST = "NO_HEIGHT_IN_REQUEST"
    NO_PROOFS_FOR_ROOT = "NO_PROOFS_FOR_ROOT"
    NO_ROOT = "NO_ROOT"
    NO_ROOT_FOR_STORE = "NO_ROOT_FOR_STORE"
    NO_START_IN_REQUEST = "NO_START_IN_REQUEST"
    NO_TX_ID_IN_REQUEST = "NO_TX_ID_IN_REQUEST"
    OLDER_BLOCK_NOT_FOUND = "OLDER_BLOCK_NOT_FOUND"
    PARENT_COIN_NOT_FOUND = "PARENT_COIN_NOT_FOUND"
    PARENT_IDS_NOT_IN_REQUEST = "PARENT_IDS_NOT_IN_REQUEST"
    PEAK_IS_NONE = "PEAK_IS_NONE"
    PRIVATE_KEY_NOT_FOUND = "PRIVATE_KEY_NOT_FOUND"
    PUZZLE_HASHES_NOT_IN_REQUEST = "PUZZLE_HASHES_NOT_IN_REQUEST"
    PUZZLE_HASH_NOT_IN_REQUEST = "PUZZLE_HASH_NOT_IN_REQUEST"
    PUZZLE_SOLUTION_FAILED = "PUZZLE_SOLUTION_FAILED"
    RECOVERY_OPTIONS_NO_LONGER_SUPPORTED = "RECOVERY_OPTIONS_NO_LONGER_SUPPORTED"
    REFRESH_INTERVAL_TOO_SHORT = "REFRESH_INTERVAL_TOO_SHORT"
    RELATIVE_TIMELOCKS_UNSUPPORTED = "RELATIVE_TIMELOCKS_UNSUPPORTED"
    REMOVE_PLOT_DIRECTORY_FAILED = "REMOVE_PLOT_DIRECTORY_FAILED"
    REQUEST_MUST_CONTAIN_EXACTLY_ONE = "REQUEST_MUST_CONTAIN_EXACTLY_ONE"
    ROYALTY_PERCENTAGE_INVALID = "ROYALTY_PERCENTAGE_INVALID"
    RPC_MODE_DROPPED = "RPC_MODE_DROPPED"
    SIGNAGE_POINT_NOT_FOUND = "SIGNAGE_POINT_NOT_FOUND"
    SOLVER_CONNECTION_FAILED = "SOLVER_CONNECTION_FAILED"
    SPEND_BUNDLE_NOT_IN_REQUEST = "SPEND_BUNDLE_NOT_IN_REQUEST"
    SP_NOT_IN_CACHE = "SP_NOT_IN_CACHE"
    STORE_ID_REQUIRED = "STORE_ID_REQUIRED"
    SUBMIT_ON_CHAIN_FALSE_BUT_SUBMITTED = "SUBMIT_ON_CHAIN_FALSE_BUT_SUBMITTED"
    TARGET_TIMES_NON_NEGATIVE = "TARGET_TIMES_NON_NEGATIVE"
    TARGET_TIMES_REQUIRED = "TARGET_TIMES_REQUIRED"
    TEST_CAT_MUST_PUSH = "TEST_CAT_MUST_PUSH"
    TOO_MANY_COINS_SELECTED = "TOO_MANY_COINS_SELECTED"
    TOO_MANY_DERIVATIONS = "TOO_MANY_DERIVATIONS"
    TOO_MANY_POOL_WALLETS = "TOO_MANY_POOL_WALLETS"
    TRADE_FAILED = "TRADE_FAILED"
    TRADE_NOT_FOUND = "TRADE_NOT_FOUND"
    TRANSACTION_FAILED = "TRANSACTION_FAILED"
    TRANSACTION_NOT_FOUND = "TRANSACTION_NOT_FOUND"
    TRANSACTION_NO_COIN_SPEND = "TRANSACTION_NO_COIN_SPEND"
    TX_NOT_IN_MEMPOOL = "TX_NOT_IN_MEMPOOL"
    UNEXPECTED_ADDRESS_PREFIX = "UNEXPECTED_ADDRESS_PREFIX"
    UNKNOWN = "UNKNOWN"
    UNKNOWN_COMMAND = "UNKNOWN_COMMAND"
    UNKNOWN_ID_TYPE = "UNKNOWN_ID_TYPE"
    UNSUPPORTED_SIGNING_MODE = "UNSUPPORTED_SIGNING_MODE"
    WALLET_NOT_FOUND = "WALLET_NOT_FOUND"
    WALLET_NOT_SYNCED = "WALLET_NOT_SYNCED"
    WALLET_NOT_SYNCED_FOR_COINS = "WALLET_NOT_SYNCED_FOR_COINS"
    WALLET_NOT_SYNCED_FOR_COIN_INFO = "WALLET_NOT_SYNCED_FOR_COIN_INFO"
    WALLET_NOT_SYNCED_FOR_DERIVATION = "WALLET_NOT_SYNCED_FOR_DERIVATION"
    WALLET_NOT_SYNCED_FOR_REWARDS = "WALLET_NOT_SYNCED_FOR_REWARDS"
    WALLET_NOT_SYNCED_FOR_SPENDABLE = "WALLET_NOT_SYNCED_FOR_SPENDABLE"
    WALLET_NOT_SYNCED_FOR_TX = "WALLET_NOT_SYNCED_FOR_TX"
    WALLET_SERVICE_NOT_INITIALIZED = "WALLET_SERVICE_NOT_INITIALIZED"
    WALLET_TYPE_CANNOT_CREATE_PUZZLE_HASHES = "WALLET_TYPE_CANNOT_CREATE_PUZZLE_HASHES"


class RpcError(Exception):
    """
    Exception carrying structured error info for RPC responses.

    message is the exact string used for the legacy `error` field.
    error_code should be an RpcErrorCodes member (e.g. RpcErrorCodes.NO_PROOFS_FOR_ROOT).
    data must be JSON-serializable so that the RPC response can be encoded.
    """

    def __init__(
        self,
        error_code: RpcErrorCodes | str,
        message: str,
        data: dict[str, Any] | None = None,
        structured_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code.value if isinstance(error_code, RpcErrorCodes) else error_code
        self.message = message
        self.data = data if data is not None else {}
        self.structured_message = structured_message if structured_message is not None else ""

    @classmethod
    def simple(
        cls,
        error_code: RpcErrorCodes | str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> RpcError:
        """
        Create an RpcError with structured_message set to message.
        Use when the human message and structured message are the same.
        Optionally pass data for extra context.
        """
        return cls(error_code, message, data=data if data is not None else {}, structured_message=message)


def structured_error_from_exception(e: Exception) -> tuple[str, StructuredError]:
    """
    Build (legacy error string, structuredError dict) for an exception.

    If e is RpcError, use its fields (code, originalError="RpcError"). Otherwise use
    code="UNKNOWN", originalError=type name (e.g. "ValueError", "Exception"), message in data.
    For non-RpcError, the legacy error string falls back to str(e) when args[0] is missing or empty.
    """
    if isinstance(e, RpcError):
        error_message = e.message
        structured: StructuredError = {
            "code": e.error_code,
            "originalError": "RpcError",
            "structuredMessage": e.structured_message,
            "data": e.data,
        }
    else:
        error_message = str(e.args[0]) if e.args else str(e)
        if not error_message:
            error_message = str(e)
        structured = {
            "code": RpcErrorCodes.UNKNOWN.value,
            "originalError": type(e).__name__,
            "structuredMessage": "",
            "data": {"message": str(e)},
        }
    return error_message, structured


def rpc_error_to_response(err: RpcError) -> dict[str, Any]:
    """
    Build the standard error response dict from an RpcError.

    Use when returning instead of raising (e.g. open_connection, connect_to_solver).
    Returns {"success": False, "error": ..., "structuredError": StructuredError}.
    """
    error_message, structured = structured_error_from_exception(err)
    return {
        "success": False,
        "error": error_message,
        "structuredError": structured,
    }
