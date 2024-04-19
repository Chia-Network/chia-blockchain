from __future__ import annotations

from hashlib import sha256
from typing import Literal, SupportsBytes, Union, cast, overload

from chia.types.blockchain_format.sized_bytes import bytes32


@overload
def std_hash(b: Union[bytes, SupportsBytes]) -> bytes32: ...


@overload
def std_hash(b: Union[bytes, SupportsBytes], skip_bytes_conversion: Literal[False]) -> bytes32: ...


@overload
def std_hash(b: bytes, skip_bytes_conversion: Literal[True]) -> bytes32: ...


def std_hash(b: Union[bytes, SupportsBytes], skip_bytes_conversion: bool = False) -> bytes32:
    """
    The standard hash used in many places.
    """
    if skip_bytes_conversion:
        # casting for hinting based on above overloads constraining the type
        return bytes32(sha256(cast(bytes, b)).digest())
    else:
        return bytes32(sha256(bytes(b)).digest())
