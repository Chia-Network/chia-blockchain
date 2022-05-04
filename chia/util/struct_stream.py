import struct
from typing import Any, BinaryIO, SupportsInt, Type, TypeVar, Union

from typing_extensions import Protocol, SupportsIndex

_T_StructStream = TypeVar("_T_StructStream", bound="StructStream")


# https://github.com/python/typeshed/blob/c2182fdd3e572a1220c70ad9c28fd908b70fb19b/stdlib/_typeshed/__init__.pyi#L68-L69
class SupportsTrunc(Protocol):
    def __trunc__(self) -> int:
        ...


def calculate_data(cls: Type[_T_StructStream]) -> Type[_T_StructStream]:
    # TODO: turn this around to calculate the PACK from the size and signedness

    cls.SIZE = struct.calcsize(cls.PACK)
    cls.BITS = cls.SIZE * 8
    cls.SIGNED = cls.PACK == cls.PACK.lower()
    if cls.SIGNED:
        cls.MAXIMUM_EXCLUSIVE = 2 ** (cls.BITS - 1)
        cls.MINIMUM = -(2 ** (cls.BITS - 1))
    else:
        cls.MAXIMUM_EXCLUSIVE = 2 ** cls.BITS
        cls.MINIMUM = 0

    return cls


class StructStream(int):
    PACK = ""
    SIZE = 0
    BITS = 0
    SIGNED = False
    MAXIMUM_EXCLUSIVE = 0
    MINIMUM = 0

    """
    Create a class that can parse and stream itself based on a struct.pack template string.
    """

    # This is just a partial exposure of the underlying int constructor.  Liskov...
    # https://github.com/python/typeshed/blob/5d07ebc864577c04366fcc46b84479dbec033921/stdlib/builtins.pyi#L181-L185
    def __init__(self, value: Union[str, bytes, SupportsInt, SupportsIndex, SupportsTrunc]) -> None:
        super().__init__()
        if not (self.MINIMUM <= self < self.MAXIMUM_EXCLUSIVE):
            raise ValueError(f"Value {self} does not fit into {type(self).__name__}")

    @classmethod
    def parse(cls: Any, f: BinaryIO) -> Any:
        bytes_to_read = cls.SIZE
        read_bytes = f.read(bytes_to_read)
        assert read_bytes is not None and len(read_bytes) == bytes_to_read
        return cls(*struct.unpack(cls.PACK, read_bytes))

    def stream(self, f):
        f.write(struct.pack(self.PACK, self))

    @classmethod
    def from_bytes(cls: Type[_T_StructStream], blob: bytes) -> _T_StructStream:  # type: ignore
        return cls(*struct.unpack(cls.PACK, blob))

    def __bytes__(self: Any) -> bytes:
        return struct.pack(self.PACK, self)
