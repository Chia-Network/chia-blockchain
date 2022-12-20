# the API to `contrib.bech32m` is an abomination unto man. This API is slightly less bad

from typing import Optional, Tuple

from hsms.contrib.bech32m import (
    bech32_decode as bech32_decode5,
    bech32_encode as bech32_encode5,
    convertbits,
    Encoding,
)


def bech32_decode(text, max_length: int = 90) -> Optional[Tuple[str, bytes, Encoding]]:
    prefix, base5_data, encoding = bech32_decode5(text, max_length)
    if prefix is None:
        return None
    base8_data = bytes(convertbits(base5_data, 5, 8))
    return prefix, base8_data, encoding


def bech32_encode(prefix: str, blob: bytes, encoding: int = Encoding.BECH32M) -> str:
    base5_bin = convertbits(blob, 8, 5)
    return bech32_encode5(prefix, base5_bin, encoding)
