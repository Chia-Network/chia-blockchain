from __future__ import annotations

from hashlib import sha256
from typing import SupportsBytes, Union

from chia.types.blockchain_format.sized_bytes import bytes32


def std_hash(bytesable: SupportsBytes) -> bytes32:
    """
    The standard hash used in many places.
    """
    return std_hash_raw(bytes(bytesable))


def std_hash_raw(buffer: Union[bytes, bytearray]) -> bytes32:
    """
    The standard hash used in many places, but without the bytes() conversion.
    """
    return bytes32(sha256(buffer).digest())
