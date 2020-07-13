import io
from typing import Any

from src.types.sized_bytes import bytes32
from src.util.clvm import sexp_from_stream, sexp_to_stream, SExp
from src.util.hash import std_hash


class Program(SExp):  # type: ignore # noqa
    """
    A thin wrapper around s-expression data intended to be invoked with "eval".
    """

    def __init__(self, v):
        if isinstance(v, SExp):
            v = v.v
        super(Program, self).__init__(v)

    @classmethod
    def parse(cls, f):
        return sexp_from_stream(f, cls.to)

    def stream(self, f):
        sexp_to_stream(self, f)

    @classmethod
    def from_bytes(cls, blob: bytes) -> Any:
        f = io.BytesIO(blob)
        return cls.parse(f)  # type: ignore # noqa

    def __bytes__(self) -> bytes:
        f = io.BytesIO()
        self.stream(f)  # type: ignore # noqa
        return f.getvalue()

    def __str__(self) -> str:
        return bytes(self).hex()

    def get_tree_hash(self) -> bytes32:
        if self.listp():
            left = self.to(self.first()).get_tree_hash()
            right = self.to(self.rest()).get_tree_hash()
            s = b"\2" + left + right
        else:
            atom = self.as_atom()
            s = b"\1" + atom
        return bytes32(std_hash(s))

    def __deepcopy__(self, memo):
        return type(self).from_bytes(bytes(self))
