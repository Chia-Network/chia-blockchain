from __future__ import annotations

import pytest

from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
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


def test_type_construction_from_correct_type() -> None:
    _ = PublicKeyBytes(bytes48(b"a" * 48))


def test_type_construction_from_correctly_sized_bytes() -> None:
    _ = PublicKeyBytes(b"a" * 48)  # type: ignore[arg-type]


def test_type_construction_from_incorrect_type_str() -> None:
    """Danger: No runtime check."""
    _ = PublicKeyBytes("a" * 48)  # type: ignore[arg-type]


def test_type_construction_from_incorrect_type_int() -> None:
    """Danger: No runtime check."""
    _ = PublicKeyBytes(48)  # type: ignore[arg-type]


def test_type_construction_from_incorrectly_sized_bytes() -> None:
    _ = PublicKeyBytes(b"a" * 32)  # type: ignore[arg-type]


def test_type_construction_from_incorrectly_sized_SizedBytes() -> None:
    _ = PublicKeyBytes(bytes32(b"a" * 32))  # type: ignore[arg-type]
