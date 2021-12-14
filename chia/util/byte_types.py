import io
from typing import BinaryIO, Type, TypeVar, TYPE_CHECKING

_T_SizedBytes = TypeVar("_T_SizedBytes", bound="SizedBytes")


def hexstr_to_bytes(input_str: str) -> bytes:
    """
    Converts a hex string into bytes, removing the 0x if it's present.
    """
    if input_str.startswith("0x") or input_str.startswith("0X"):
        return bytes.fromhex(input_str[2:])
    return bytes.fromhex(input_str)


class SizedBytes(bytes):
    """A streamable type that subclasses "bytes" but requires instances
    to be a certain, fixed size specified by the `._size` class attribute.
    """

    _size = 0

    @staticmethod
    def __new__(cls: Type[_T_SizedBytes], v) -> _T_SizedBytes:
        v = bytes(v)
        if not isinstance(v, bytes) or len(v) != cls._size:
            raise ValueError("bad %s initializer %s" % (cls.__name__, v))
        return bytes.__new__(cls, v)

    @classmethod
    def parse(cls: Type[_T_SizedBytes], f: BinaryIO) -> _T_SizedBytes:
        b = f.read(cls._size)
        assert len(b) == cls._size
        return cls(b)

    def stream(self, f):
        f.write(self)

    @classmethod
    def from_bytes(cls: Type[_T_SizedBytes], blob: bytes) -> _T_SizedBytes:
        # pylint: disable=no-member
        f = io.BytesIO(blob)
        result = cls.parse(f)
        assert f.read() == b""
        return result

    @classmethod
    def from_hexstr(cls: Type[_T_SizedBytes], input_str: str) -> _T_SizedBytes:
        if input_str.startswith("0x") or input_str.startswith("0X"):
            return cls.fromhex(input_str[2:])
        return cls.fromhex(input_str)

    def __bytes__(self) -> bytes:
        f = io.BytesIO()
        self.stream(f)
        return bytes(f.getvalue())

    def __str__(self):
        return self.hex()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, str(self))

    if TYPE_CHECKING:
        # TODO: This stub implements a fix already merged into typeshed but not yet
        #       released in a new mypy version.  Once released this should be removed.
        #       https://github.com/python/typeshed/pull/6201
        @classmethod
        def fromhex(cls: Type[_T_SizedBytes], __s: str) -> _T_SizedBytes:
            ...
