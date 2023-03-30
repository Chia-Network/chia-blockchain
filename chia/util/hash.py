from __future__ import annotations

from hashlib import sha256
from typing import Union

from chia.types.blockchain_format.sized_bytes import bytes32


def std_hash(buffer: Union[bytes, bytearray]) -> bytes32:
    """
    The standard hash used in many places.
    """
    return bytes32(sha256(buffer).digest())
