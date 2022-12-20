from typing import Any, BinaryIO

from .bin_methods import bin_methods
from .hexbytes import hexbytes


def make_sized_bytes(size):
    """
    Create a streamable type that subclasses "hexbytes" but requires instances
    to be a certain, fixed size.
    """
    name = "bytes%d" % size

    def __new__(self, v):
        v = bytes(v)
        if not isinstance(v, bytes) or len(v) != size:
            raise ValueError("bad %s initializer %s" % (name, v))
        return hexbytes.__new__(self, v)

    @classmethod
    def parse(cls, f: BinaryIO) -> Any:
        b = f.read(size)
        assert len(b) == size
        return cls(b)

    def stream(self, f):
        f.write(self)

    def __str__(self):
        return self.hex()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, str(self))

    namespace = dict(
        __new__=__new__, parse=parse, stream=stream, __str__=__str__, __repr__=__repr__
    )

    cls = type(name, (hexbytes, bin_methods), namespace)

    return cls
