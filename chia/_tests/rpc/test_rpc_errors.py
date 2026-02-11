"""
Tests for chia.rpc.rpc_errors: RpcError and structured_error_from_exception.
"""

from __future__ import annotations

from chia.rpc.rpc_errors import RpcError, RpcErrorCodes, structured_error_from_exception


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


def test_rpc_error_codes_values_match_names() -> None:
    """Every RpcErrorCodes member has value == name (catches copy-paste typos in the enum)."""
    for member in RpcErrorCodes:
        assert member.value == member.name, f"{member.name} has mismatched value {member.value!r}"
