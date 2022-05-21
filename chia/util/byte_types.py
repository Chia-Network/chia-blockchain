from typing import BinaryIO, Iterable, SupportsBytes, Type, TypeVar, Union

from typing_extensions import SupportsIndex

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

    # This is just a partial exposure of the underlying int constructor.  Liskov...
    # https://github.com/python/typeshed/blob/f8547a3f3131de90aa47005358eb3394e79cfa13/stdlib/builtins.pyi#L483-L493
    def __init__(self, v: Union[Iterable[SupportsIndex], SupportsBytes]) -> None:
        # v is unused here and that is ok since .__new__() seems to have already
        # processed the parameter when creating the instance of the class.  We have no
        # additional special action to take here beyond verifying that the newly
        # created instance satisfies the length limitation of the particular subclass.
        super().__init__()
        if len(self) != self._size:
            raise ValueError("bad %s initializer %s" % (type(self).__name__, v))

    @classmethod
    def parse(cls: Type[_T_SizedBytes], f: BinaryIO) -> _T_SizedBytes:
        b = f.read(cls._size)
        return cls(b)

    def stream(self, f: BinaryIO) -> None:
        f.write(self)

    @classmethod
    def from_bytes(cls: Type[_T_SizedBytes], blob: bytes) -> _T_SizedBytes:
        return cls(blob)

    @classmethod
    def from_hexstr(cls: Type[_T_SizedBytes], input_str: str) -> _T_SizedBytes:
        if input_str.startswith("0x") or input_str.startswith("0X"):
            return cls.fromhex(input_str[2:])
        return cls.fromhex(input_str)

    def __str__(self) -> str:
        return self.hex()

    def __repr__(self) -> str:
        return "<%s: %s>" % (self.__class__.__name__, str(self))
