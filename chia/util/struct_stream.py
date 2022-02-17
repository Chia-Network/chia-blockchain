import io
import struct
from typing import Any, BinaryIO, SupportsInt, Type, TypeVar, Union

from typing_extensions import Protocol, SupportsIndex

_T_StructStream = TypeVar("_T_StructStream", bound="StructStream")


# https://github.com/python/typeshed/blob/c2182fdd3e572a1220c70ad9c28fd908b70fb19b/stdlib/_typeshed/__init__.pyi#L68-L69
class SupportsTrunc(Protocol):
    def __trunc__(self) -> int:
        ...


class StructStream(int):
    PACK = ""

    """
    Create a class that can parse and stream itself based on a struct.pack template string.
    """

    # This is just a partial exposure of the underlying int constructor.  Liskov...
    # https://github.com/python/typeshed/blob/5d07ebc864577c04366fcc46b84479dbec033921/stdlib/builtins.pyi#L181-L185
    def __new__(
        cls: Type[_T_StructStream], value: Union[str, bytes, SupportsInt, SupportsIndex, SupportsTrunc]
    ) -> _T_StructStream:
        value = int(value)
        try:
            v1 = struct.unpack(cls.PACK, struct.pack(cls.PACK, value))[0]
            if value != v1:
                raise ValueError(f"Value {value} does not fit into {cls.__name__}")
        except Exception:
            bits = struct.calcsize(cls.PACK) * 8
            raise ValueError(
                f"Value {value} of size {value.bit_length()} does not fit into " f"{cls.__name__} of size {bits}"
            )
        return int.__new__(cls, value)

    @classmethod
    def parse(cls: Any, f: BinaryIO) -> Any:
        bytes_to_read = struct.calcsize(cls.PACK)
        read_bytes = f.read(bytes_to_read)
        assert read_bytes is not None and len(read_bytes) == bytes_to_read
        return cls(*struct.unpack(cls.PACK, read_bytes))

    def stream(self, f):
        f.write(struct.pack(self.PACK, self))

    @classmethod
    def from_bytes(cls: Any, blob: bytes) -> Any:  # type: ignore
        f = io.BytesIO(blob)
        result = cls.parse(f)
        assert f.read() == b""
        return result

    def __bytes__(self: Any) -> bytes:
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())
