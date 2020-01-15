from clvm import to_sexp_f
from clvm.serialize import sexp_from_stream, sexp_to_stream
from clvm.subclass_sexp import BaseSExp

from src.types.sized_bytes import bytes32
from .Hash import std_hash

from ...atoms import bin_methods, hash_pointer

SExp = to_sexp_f(1).__class__


class Program(SExp, bin_methods):
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

    def __str__(self):
        return bytes(self).hex()


ProgramHash: bytes32 = hash_pointer(Program, std_hash)
