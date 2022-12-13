from __future__ import annotations

from typing import NewType, TypeVar

from typing_extensions import Protocol

from chia.types.blockchain_format.sized_bytes import bytes48

_T = TypeVar("_T", covariant=True)


PublicKeyBytes = NewType("PublicKeyBytes", bytes48)


class BytesToProtocol(Protocol[_T]):
    def __call__(self, __positional_only: bytes) -> _T:
        ...


"""
These conversion functions of the form bytes_to_TYPENAME
should be used at the border between native code (eg. Rust and C++) and Python only.

Use bytes_to_TypeName() for bytes coming from native code into the Python program.
Use the TypeName() constructor if you are constructing e.g. a bytes32 from within Python, perhaps for use in a test.

Note the type signature of the conversion functions:
```
    def bytes_to_PublicKeyBytes(input_bytes: bytes) -> PublicKeyBytes:
```

Native modules are only able to return native Python types by default, thus we get `bytes`, and not `bytes32`
from those libraries.

"""

bytes_to_PublicKeyBytes: BytesToProtocol[PublicKeyBytes] = bytes48
