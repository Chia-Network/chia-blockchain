from __future__ import annotations

import pytest

from chia.types.blockchain_format.sized_bytes import bytes48
from chia.types.border_types import PublicKeyBytes, bytes_to_PublicKeyBytes


def test_wrong_input_type() -> None:
    with pytest.raises(TypeError):
        _ = bytes_to_PublicKeyBytes("hi")  # type: ignore[arg-type]


def test_underlying_typecheck() -> None:
    with pytest.raises(ValueError):
        _ = bytes_to_PublicKeyBytes(b"")


def test_incorrect_number_of_bytes() -> None:
    with pytest.raises(ValueError):
        _ = bytes_to_PublicKeyBytes(b"a" * 32)


def test_type_conversion() -> None:
    a = bytes_to_PublicKeyBytes(b"a" * 48)
    assert a == PublicKeyBytes(
        bytes48(
            bytes.fromhex(
                "6161616161616161616161616161616161616161616161616161616161616161" "61616161616161616161616161616161"
            )
        )
    )
