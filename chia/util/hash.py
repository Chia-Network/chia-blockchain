from __future__ import annotations

from hashlib import sha256

from chia.types.blockchain_format.sized_bytes import bytes32


def std_hash(b, skip_bytes_conversion: bool = False) -> bytes32:
    """
    The standard hash used in many places.
    """
    if skip_bytes_conversion:
        return bytes32(sha256(b).digest())
    else:
        return bytes32(sha256(bytes(b)).digest())
