"""
Tests for chia.rpc.rpc_errors: RpcError and structured_error_from_exception.
"""

from __future__ import annotations

from chia.rpc.rpc_errors import RpcError, RpcErrorCodes, structured_error_from_exception
from chia.util.errors import ApiError as UtilApiError
from chia.util.errors import ConsensusError, Err, ProtocolError, TimestampError, ValidationError


def test_rpc_error_attributes_and_defaults() -> None:
    """Full constructor sets all fields; omitted kwargs get sensible defaults."""
    err = RpcError(
        RpcErrorCodes.BLOCK_NOT_FOUND,
        "Block 0xabc not found",
        data={"header_hash": "abc"},
        structured_message="Block not found",
    )
    assert err.error_code == "BLOCK_NOT_FOUND"
    assert err.message == "Block 0xabc not found"
    assert err.data == {"header_hash": "abc"}
    assert err.structured_message == "Block not found"
    assert str(err) == "Block 0xabc not found"

    minimal = RpcError(RpcErrorCodes.UNKNOWN, "oops")
    assert minimal.data == {}
    assert minimal.structured_message == ""


def test_rpc_error_simple() -> None:
    """RpcError.simple copies message into structured_message and accepts optional data."""
    err = RpcError.simple(RpcErrorCodes.NO_BLOCKS_IN_CHAIN, "No blocks in the chain")
    assert err.error_code == "NO_BLOCKS_IN_CHAIN"
    assert err.structured_message == err.message
    assert err.data == {}

    err_with_data = RpcError.simple(RpcErrorCodes.BLOCK_NOT_FOUND, "Block not found", data={"header_hash": "abc"})
    assert err_with_data.data == {"header_hash": "abc"}


def test_structured_error_from_rpc_error() -> None:
    """RpcError produces a full structured dict."""
    rpc_err = RpcError(
        RpcErrorCodes.BLOCK_NOT_FOUND,
        "Block 0xabc not found",
        data={"header_hash": "abc"},
        structured_message="Block not found",
    )
    error_message, structured = structured_error_from_exception(rpc_err)
    assert error_message == "Block 0xabc not found"
    assert structured == {
        "code": "BLOCK_NOT_FOUND",
        "message": "Block not found",
        "data": {"header_hash": "abc"},
    }


def test_structured_error_from_validation_error() -> None:
    """ValidationError preserves Err code and error_msg."""
    exc = ValidationError(Err.INVALID_SPEND_BUNDLE, "bundle is empty")
    _msg, structured = structured_error_from_exception(exc)
    assert structured["code"] == "VALIDATION_ERROR"
    assert structured["data"]["error_code"] == Err.INVALID_SPEND_BUNDLE.value

    assert structured["data"]["error_msg"] == "bundle is empty"

    exc_no_msg = ValidationError(Err.BLOCK_COST_EXCEEDS_MAX)
    _, structured_no_msg = structured_error_from_exception(exc_no_msg)
    assert structured_no_msg["code"] == "VALIDATION_ERROR"
    assert structured_no_msg["data"]["error_code"] == Err.BLOCK_COST_EXCEEDS_MAX.value

    assert "error_msg" not in structured_no_msg["data"]


def test_structured_error_from_timestamp_error() -> None:
    """TimestampError preserves its fixed Err code."""
    exc = TimestampError()
    _msg, structured = structured_error_from_exception(exc)
    assert structured["code"] == "TIMESTAMP_ERROR"
    assert structured["data"]["error_code"] == Err.TIMESTAMP_TOO_FAR_IN_FUTURE.value


def test_structured_error_from_consensus_error() -> None:
    """ConsensusError preserves Err code and stringified errors list."""
    exc = ConsensusError(Err.INVALID_BLOCK_SOLUTION, ["detail1", "detail2"])
    _msg, structured = structured_error_from_exception(exc)
    assert structured["code"] == "CONSENSUS_ERROR"
    assert structured["data"]["error_code"] == Err.INVALID_BLOCK_SOLUTION.value

    assert structured["data"]["errors"] == ["detail1", "detail2"]

    exc_no_errors = ConsensusError(Err.UNKNOWN)
    _, structured_no_errors = structured_error_from_exception(exc_no_errors)
    assert structured_no_errors["data"]["error_code"] == Err.UNKNOWN.value

    assert "errors" not in structured_no_errors["data"]


def test_structured_error_from_protocol_error() -> None:
    """ProtocolError preserves Err code and stringified errors list."""
    exc = ProtocolError(Err.INVALID_PROTOCOL_MESSAGE, ["bad message"])
    _msg, structured = structured_error_from_exception(exc)
    assert structured["code"] == "PROTOCOL_ERROR"
    assert structured["data"]["error_code"] == Err.INVALID_PROTOCOL_MESSAGE.value

    assert structured["data"]["errors"] == ["bad message"]

    exc_no_errors = ProtocolError(Err.UNKNOWN)
    _, structured_no_errors = structured_error_from_exception(exc_no_errors)
    assert "errors" not in structured_no_errors["data"]


def test_structured_error_from_api_error() -> None:
    """ApiError preserves Err code."""
    exc = UtilApiError(Err.NO_TRANSACTIONS_WHILE_SYNCING, "node is syncing")
    _msg, structured = structured_error_from_exception(exc)
    assert structured["code"] == "API_ERROR"
    assert structured["data"]["error_code"] == Err.NO_TRANSACTIONS_WHILE_SYNCING.value


def test_structured_error_from_assertion_error() -> None:
    """AssertionError maps to INTERNAL_ERROR with no extra data."""
    exc = AssertionError("invariant violated")
    msg, structured = structured_error_from_exception(exc)
    assert msg == "invariant violated"
    assert structured["code"] == "INTERNAL_ERROR"
    assert structured["data"] == {}


def test_structured_error_from_unknown_exception() -> None:
    """Unrecognized exceptions fall back to UNKNOWN."""
    msg, structured = structured_error_from_exception(ValueError("something went wrong"))
    assert msg == "something went wrong"
    assert structured["code"] == "UNKNOWN"
    assert structured["data"] == {}


def test_rpc_error_codes_values_match_names() -> None:
    """Every RpcErrorCodes member has value == name (catches copy-paste typos in the enum)."""
    for member in RpcErrorCodes:
        assert member.value == member.name, f"{member.name} has mismatched value {member.value!r}"
