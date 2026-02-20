"""Structured RPC errors. Values in ``data`` must be JSON-serializable."""

from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict


class StructuredError(TypedDict):
    code: str
    message: str
    data: dict[str, Any]


class RpcErrorCodes(str, Enum):
    API_ERROR = "API_ERROR"
    BLOCK_DOES_NOT_EXIST = "BLOCK_DOES_NOT_EXIST"
    BLOCK_HASH_NOT_FOUND = "BLOCK_HASH_NOT_FOUND"
    BLOCK_HEIGHT_NOT_FOUND = "BLOCK_HEIGHT_NOT_FOUND"
    BLOCK_IN_FORK = "BLOCK_IN_FORK"
    BLOCK_NOT_FOUND = "BLOCK_NOT_FOUND"
    COIN_RECORD_NOT_FOUND = "COIN_RECORD_NOT_FOUND"
    CONSENSUS_ERROR = "CONSENSUS_ERROR"
    EOS_NOT_IN_CACHE = "EOS_NOT_IN_CACHE"
    HEADER_HASH_NOT_IN_REQUEST = "HEADER_HASH_NOT_IN_REQUEST"
    HEIGHT_NOT_IN_BLOCKCHAIN = "HEIGHT_NOT_IN_BLOCKCHAIN"
    HINT_NOT_IN_REQUEST = "HINT_NOT_IN_REQUEST"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INVALID_BLOCK_OR_GENERATOR = "INVALID_BLOCK_OR_GENERATOR"
    INVALID_COST = "INVALID_COST"
    INVALID_HEIGHT_FOR_COIN = "INVALID_HEIGHT_FOR_COIN"
    INVALID_NETWORK_SPACE_REQUEST = "INVALID_NETWORK_SPACE_REQUEST"
    NAME_NOT_IN_REQUEST = "NAME_NOT_IN_REQUEST"
    NAMES_NOT_IN_REQUEST = "NAMES_NOT_IN_REQUEST"
    NEW_AND_OLD_MUST_DIFFER = "NEW_AND_OLD_MUST_DIFFER"
    NEWER_BLOCK_NOT_FOUND = "NEWER_BLOCK_NOT_FOUND"
    NO_BLOCKS_IN_CHAIN = "NO_BLOCKS_IN_CHAIN"
    NO_COIN_NAME_IN_REQUEST = "NO_COIN_NAME_IN_REQUEST"
    NO_END_IN_REQUEST = "NO_END_IN_REQUEST"
    NO_HEADER_HASH_IN_REQUEST = "NO_HEADER_HASH_IN_REQUEST"
    NO_HEIGHT_IN_REQUEST = "NO_HEIGHT_IN_REQUEST"
    NO_START_IN_REQUEST = "NO_START_IN_REQUEST"
    NO_TX_ID_IN_REQUEST = "NO_TX_ID_IN_REQUEST"
    OLDER_BLOCK_NOT_FOUND = "OLDER_BLOCK_NOT_FOUND"
    PARENT_IDS_NOT_IN_REQUEST = "PARENT_IDS_NOT_IN_REQUEST"
    PEAK_IS_NONE = "PEAK_IS_NONE"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    PUZZLE_HASH_NOT_IN_REQUEST = "PUZZLE_HASH_NOT_IN_REQUEST"
    PUZZLE_HASHES_NOT_IN_REQUEST = "PUZZLE_HASHES_NOT_IN_REQUEST"
    PUZZLE_SOLUTION_FAILED = "PUZZLE_SOLUTION_FAILED"
    REQUEST_MUST_CONTAIN_EXACTLY_ONE = "REQUEST_MUST_CONTAIN_EXACTLY_ONE"
    SP_NOT_IN_CACHE = "SP_NOT_IN_CACHE"
    SPEND_BUNDLE_NOT_IN_REQUEST = "SPEND_BUNDLE_NOT_IN_REQUEST"
    TARGET_TIMES_NON_NEGATIVE = "TARGET_TIMES_NON_NEGATIVE"
    TARGET_TIMES_REQUIRED = "TARGET_TIMES_REQUIRED"
    TIMESTAMP_ERROR = "TIMESTAMP_ERROR"
    TRANSACTION_FAILED = "TRANSACTION_FAILED"
    TX_NOT_IN_MEMPOOL = "TX_NOT_IN_MEMPOOL"
    UNKNOWN = "UNKNOWN"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class RpcError(Exception):
    """Exception carrying a structured error code, message, and data for RPC responses."""

    def __init__(
        self,
        error_code: RpcErrorCodes,
        message: str,
        data: dict[str, Any] | None = None,
        structured_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code.value
        self.message = message
        self.data = data if data is not None else {}
        self.structured_message = structured_message if structured_message is not None else ""

    @classmethod
    def simple(
        cls,
        error_code: RpcErrorCodes,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> RpcError:
        """Create an RpcError where structured_message equals message."""
        return cls(error_code, message, data=data if data is not None else {}, structured_message=message)


def structured_error_from_exception(e: Exception) -> tuple[str, StructuredError]:
    """Return (legacy error string, StructuredError) for any exception."""
    from chia.util.errors import ApiError as UtilApiError
    from chia.util.errors import ConsensusError, ProtocolError, TimestampError, ValidationError

    if isinstance(e, RpcError):
        error_message = e.message
        structured: StructuredError = {
            "code": e.error_code,
            "message": e.structured_message,
            "data": e.data,
        }
    else:
        error_message = str(e.args[0]) if e.args else str(e)
        if not error_message:
            error_message = str(e)

        if isinstance(e, ValidationError):
            code = RpcErrorCodes.VALIDATION_ERROR.value
            data: dict[str, Any] = {"error_code": e.code.value}
            if e.error_msg:
                data["error_msg"] = e.error_msg
        elif isinstance(e, TimestampError):
            code = RpcErrorCodes.TIMESTAMP_ERROR.value
            data = {"error_code": e.code.value}
        elif isinstance(e, ConsensusError):
            code = RpcErrorCodes.CONSENSUS_ERROR.value
            data = {"error_code": e.code.value}
            if e.errors:
                data["errors"] = [str(x) for x in e.errors]
        elif isinstance(e, ProtocolError):
            code = RpcErrorCodes.PROTOCOL_ERROR.value
            data = {"error_code": e.code.value}
            if e.errors:
                data["errors"] = [str(x) for x in e.errors]
        elif isinstance(e, UtilApiError):
            code = RpcErrorCodes.API_ERROR.value
            data = {"error_code": e.code.value}
        elif isinstance(e, AssertionError):
            code = RpcErrorCodes.INTERNAL_ERROR.value
            data = {}
        else:
            code = RpcErrorCodes.UNKNOWN.value
            data = {}

        structured = {
            "code": code,
            "message": error_message,
            "data": data,
        }
    return error_message, structured
