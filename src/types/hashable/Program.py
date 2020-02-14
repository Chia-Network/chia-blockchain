import io
from typing import Any

from clvm import to_sexp_f
from clvm.serialize import sexp_from_stream, sexp_to_stream
from clvm.subclass_sexp import BaseSExp

from src.types.sized_bytes import bytes32
from src.util.hash import std_hash

SExp = to_sexp_f(1).__class__


class Program(SExp):  # type: ignore # noqa
    """
    A thin wrapper around s-expression data intended to be invoked with "eval".
    """

    code: BaseSExp

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

    def get_hash(self) -> bytes32:
        # print("Bytes self", bytes(self))
        return bytes32(std_hash(bytes(self)))
