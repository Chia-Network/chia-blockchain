"""
Tests for chia.rpc.rpc_errors: RpcError, structured_error_from_exception, and rpc_error_to_response.
"""

from __future__ import annotations

from chia.rpc.rpc_errors import RpcError, RpcErrorCodes, rpc_error_to_response, structured_error_from_exception


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

    err_with_data = RpcError.simple(RpcErrorCodes.CONNECTION_FAILED, "could not connect", data={"host": "127.0.0.1"})
    assert err_with_data.data == {"host": "127.0.0.1"}


def test_structured_error_from_exception() -> None:
    """RpcError produces a full structured dict; non-RpcError falls back to code=UNKNOWN."""
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

    generic_msg, generic_structured = structured_error_from_exception(ValueError("something went wrong"))
    assert generic_msg == "something went wrong"
    assert generic_structured["code"] == "UNKNOWN"
    assert generic_structured["data"] == {}


def test_rpc_error_to_response() -> None:
    """rpc_error_to_response builds a complete error response dict."""
    err = RpcError(
        RpcErrorCodes.CONNECTION_FAILED,
        "could not connect to 127.0.0.1:8444",
        data={"target": "127.0.0.1:8444"},
        structured_message="Could not connect to target",
    )
    response = rpc_error_to_response(err)
    assert response["success"] is False
    assert response["error"] == "could not connect to 127.0.0.1:8444"
    assert response["structuredError"]["code"] == "CONNECTION_FAILED"
    assert response["structuredError"]["message"] == "Could not connect to target"
    assert response["structuredError"]["data"] == {"target": "127.0.0.1:8444"}


def test_rpc_error_codes_values_match_names() -> None:
    """Every RpcErrorCodes member has value == name (catches copy-paste typos in the enum)."""
    for member in RpcErrorCodes:
        assert member.value == member.name, f"{member.name} has mismatched value {member.value!r}"
