import io
from typing import Any, List, Set

from src.types.sized_bytes import bytes32
from src.util.clvm import run_program, sexp_from_stream, sexp_to_stream, SExp
from src.util.hash import std_hash

from clvm_tools.curry import curry


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

    def _tree_hash(self, precalculated: Set[bytes32]) -> bytes32:
        """
        Hash values in `precalculated` are presumed to have been hashed already.
        """
        if self.listp():
            left = self.to(self.first())._tree_hash(precalculated)
            right = self.to(self.rest())._tree_hash(precalculated)
            s = b"\2" + left + right
        else:
            atom = self.as_atom()
            if atom in precalculated:
                return bytes32(atom)
            s = b"\1" + atom
        return bytes32(std_hash(s))

    def get_tree_hash(self, *args: List[bytes32]) -> bytes32:
        """
        Any values in `args` that appear in the tree
        are presumed to have been hashed already.
        """
        return self._tree_hash(set(args))

    def run(self, args) -> "Program":
        prog_args = Program.to(args)
        cost, r = run_program(self, prog_args)
        return Program.to(r)

    def curry(self, *args) -> "Program":
        cost, r = curry(self, list(args))
        return Program.to(r)

    def __deepcopy__(self, memo):
        return type(self).from_bytes(bytes(self))
