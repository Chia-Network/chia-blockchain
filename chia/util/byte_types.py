from typing import Any, BinaryIO


def hexstr_to_bytes(input_str: str) -> bytes:
    """
    Converts a hex string into bytes, removing the 0x if it's present.
    """
    if input_str.startswith(("0x", "0X")):
        return bytes.fromhex(input_str[2:])
    return bytes.fromhex(input_str)


def make_sized_bytes(size: int):
    """
    Create a streamable type that subclasses "bytes" but requires instances
    to be a certain, fixed size.
    """
    name = f"bytes{size}"

    def __new__(cls, v):
        self = bytes.__new__(cls, v)
        if len(self) != size:
            raise ValueError(f"bad {name} initializer {v}")
        return self

    @classmethod  # type: ignore
    def parse(cls, f: BinaryIO) -> Any:
        b = f.read(size)
        return cls(b)

    def stream(self, f):
        f.write(self)

    @classmethod  # type: ignore
    def from_bytes(cls: Any, blob: bytes) -> Any:
        return cls(blob)

    def __str__(self):
        return self.hex()

    def __repr__(self):
        return f"<{name}: {self}>"

    namespace = dict(
        __new__=__new__,
        parse=parse,
        stream=stream,
        from_bytes=from_bytes,
        __str__=__str__,
        __repr__=__repr__,
    )

    return type(name, (bytes,), namespace)
