from __future__ import annotations

from typing import NewType

from chia.types.blockchain_format.sized_bytes import bytes32, bytes48

CoinID = NewType("CoinID", bytes32)
PublicKeyBytes = NewType("PublicKeyBytes", bytes48)
PuzzleHash = NewType("PuzzleHash", bytes32)
SpendBundleID = NewType("SpendBundleID", bytes32)
TransactionRecordID = NewType("TransactionRecordID", bytes32)

"""
These conversion functions should be used at the border between native code (eg. Rust and C++) and Python

Use bytes_to_TypeName() for bytes coming from native code into the Python program.
Use the TypeName() constructor if you are constructing e.g. a bytes32 from within Python, perhaps for use in a test.

Note the type signature of the conversion functions:
```
    def bytes_to_PublicKeyBytes(input_bytes: bytes) -> PublicKeyBytes:
```

Native modules are only able to return native Python types by default, thus we get `bytes`, and not `bytes32`
from those libraries.

"""


def bytes_to_PublicKeyBytes(input_bytes: bytes) -> PublicKeyBytes:
    return PublicKeyBytes(bytes48(input_bytes))


def bytes_to_CoinID(input_bytes: bytes) -> CoinID:
    return CoinID(bytes32(input_bytes))


def bytes_to_SpendBundleID(input_bytes: bytes) -> SpendBundleID:
    return SpendBundleID(bytes32(input_bytes))
