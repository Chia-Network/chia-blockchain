from __future__ import annotations

import pytest

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.borderlands import PrivateKeyBytes, bytes_to_PrivateKeyBytes


def test_wrong_input_type() -> None:
    with pytest.raises(TypeError):
        _ = bytes_to_PrivateKeyBytes("hi")  # type: ignore[arg-type]


def test_unknown_type() -> None:
    with pytest.raises(ValueError):
        _ = bytes_to_PrivateKeyBytes(b"")


def test_underlying_typecheck() -> None:
    with pytest.raises(ValueError):
        _ = bytes_to_PrivateKeyBytes(b"")


def test_type_conversion() -> None:
    a = bytes_to_PrivateKeyBytes(b"a" * 32)
    assert a == PrivateKeyBytes(
        bytes32(bytes.fromhex("6161616161616161616161616161616161616161616161616161616161616161"))
    )
