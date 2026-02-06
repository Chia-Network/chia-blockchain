"""
Tests for chia.rpc.rpc_errors: RpcError, structured_error_from_exception, and rpc_error_to_response.
"""

from __future__ import annotations

import pytest

from chia.rpc.rpc_errors import RpcError, RpcErrorCodes, rpc_error_to_response, structured_error_from_exception


def test_rpc_error_attributes() -> None:
    err = RpcError(
        RpcErrorCodes.COIN_NOT_FOUND,
        "Could not find coin with ID abc123",
        data={"target_coin_id": "abc123"},
        structured_message="Could not find coin with ID",
    )
    assert err.error_code == "COIN_NOT_FOUND"
    assert err.message == "Could not find coin with ID abc123"
    assert err.data == {"target_coin_id": "abc123"}
    assert err.structured_message == "Could not find coin with ID"
    assert str(err) == "Could not find coin with ID abc123"


def test_rpc_error_defaults() -> None:
    err = RpcError(RpcErrorCodes.WALLET_NOT_SYNCED, "Wallet needs to be fully synced.")
    assert err.data == {}
    assert err.structured_message == ""


def test_rpc_error_simple() -> None:
    """RpcError.simple sets structured_message to message and data to {}."""
    err = RpcError.simple(RpcErrorCodes.CANNOT_SPLIT_NFT, "Cannot split coins from non-fungible wallet types")
    assert err.error_code == "CANNOT_SPLIT_NFT"
    assert err.message == "Cannot split coins from non-fungible wallet types"
    assert err.structured_message == err.message
    assert err.data == {}
    error_message, structured = structured_error_from_exception(err)
    assert error_message == err.message
    assert structured["message"] == err.message
    assert structured["code"] == "CANNOT_SPLIT_NFT"


def test_rpc_error_simple_with_data() -> None:
    """RpcError.simple accepts optional data and it appears in structured output."""
    err = RpcError.simple(
        RpcErrorCodes.CONNECTION_FAILED,
        "could not connect",
        data={"host": "127.0.0.1", "port": 8444},
    )
    assert err.error_code == "CONNECTION_FAILED"
    assert err.data == {"host": "127.0.0.1", "port": 8444}
    _msg, structured = structured_error_from_exception(err)
    assert structured["code"] == "CONNECTION_FAILED"
    assert structured["data"] == {"host": "127.0.0.1", "port": 8444}


def test_structured_error_from_exception_rpc_error() -> None:
    err = RpcError(
        RpcErrorCodes.BLOCK_NOT_FOUND,
        "Block 0xabc not found",
        data={"header_hash": "abc"},
        structured_message="Block not found",
    )
    error_message, structured = structured_error_from_exception(err)
    assert error_message == "Block 0xabc not found"
    assert structured == {
        "code": "BLOCK_NOT_FOUND",
        "message": "Block not found",
        "data": {"header_hash": "abc"},
    }


def test_structured_error_from_exception_unknown() -> None:
    err = ValueError("something went wrong")
    error_message, structured = structured_error_from_exception(err)
    assert error_message == "something went wrong"
    assert structured["code"] == "UNKNOWN"
    assert structured["message"] == "something went wrong"
    assert structured["data"] == {}


def test_structured_error_from_exception_empty_args() -> None:
    err = ValueError()
    error_message, structured = structured_error_from_exception(err)
    assert error_message == ""
    assert structured["code"] == "UNKNOWN"
    assert structured["data"] == {}


def test_structured_error_from_exception_uses_unknown_code() -> None:
    """Non-RpcError exceptions use code='UNKNOWN'."""
    err = Exception("generic failure")
    _msg, structured = structured_error_from_exception(err)
    assert structured["code"] == "UNKNOWN"
    err2 = KeyError("missing_key")
    _msg2, structured2 = structured_error_from_exception(err2)
    assert structured2["code"] == "UNKNOWN"


def test_structured_error_from_exception_raw_string_code() -> None:
    """RpcError accepts a raw string error_code (e.g. for ad-hoc or test codes)."""
    err = RpcError("CUSTOM_CODE", "custom message", data={"key": "value"})
    _msg, structured = structured_error_from_exception(err)
    assert structured["code"] == "CUSTOM_CODE"
    assert structured["data"] == {"key": "value"}


def test_structured_error_from_exception_non_string_arg() -> None:
    """Non-RpcError exception with a non-string args[0] (e.g. int) still returns a str error_message."""
    err = ValueError(42)
    error_message, structured = structured_error_from_exception(err)
    assert error_message == "42"
    assert isinstance(error_message, str)
    assert structured["code"] == "UNKNOWN"
    assert structured["data"] == {}


def test_rpc_error_to_response() -> None:
    """rpc_error_to_response builds the same dict shape as a raised RpcError would produce."""
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


@pytest.mark.parametrize("member", RpcErrorCodes)
def test_rpc_error_codes_values_match_names(member: RpcErrorCodes) -> None:
    """Every RpcErrorCodes member has value == name (catches typos in the enum)."""
    assert member.value == member.name


def test_structured_error_keys_are_exhaustive() -> None:
    """Structured error dicts contain exactly {code, message, data} -- no extra or missing keys."""
    # RpcError path
    err = RpcError(RpcErrorCodes.BLOCK_NOT_FOUND, "not found", data={"h": "abc"}, structured_message="Block not found")
    _msg, structured = structured_error_from_exception(err)
    assert set(structured.keys()) == {"code", "message", "data"}

    # Non-RpcError path
    err2 = ValueError("oops")
    _msg2, structured2 = structured_error_from_exception(err2)
    assert set(structured2.keys()) == {"code", "message", "data"}


def test_structured_error_from_exception_empty_string_arg() -> None:
    """Exception with empty string arg[0] exercises the 'if not error_message' fallback branch."""
    err = ValueError("")
    error_message, structured = structured_error_from_exception(err)
    # str(ValueError("").args[0]) is "", which is falsy, so falls through to str(e) which is also ""
    assert error_message == ""
    assert structured["code"] == "UNKNOWN"
    assert structured["message"] == ""


def test_rpc_error_is_exception_subclass() -> None:
    """RpcError must be catchable as Exception (critical for RPC error handlers)."""
    err = RpcError.simple(RpcErrorCodes.UNKNOWN, "test")
    assert isinstance(err, Exception)
    # Verify it's actually catchable in an except Exception block
    caught = False
    try:
        raise err
    except Exception:
        caught = True
    assert caught
