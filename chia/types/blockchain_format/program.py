import io
from typing import List, Optional, Set, Tuple

from clvm import KEYWORD_FROM_ATOM, KEYWORD_TO_ATOM, SExp
from clvm import run_program as default_run_program
from clvm.casts import int_from_bytes
from clvm.EvalError import EvalError
from clvm.operators import OP_REWRITE, OPERATOR_LOOKUP
from clvm.serialize import sexp_buffer_from_stream, sexp_from_stream, sexp_to_stream
from clvm_rs import STRICT_MODE, deserialize_and_run_program
from clvm_tools.curry import curry, uncurry

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash


def run_program(
    program,
    args,
    operator_lookup=OPERATOR_LOOKUP,
    max_cost=None,
    pre_eval_f=None,
):
    return default_run_program(
        program,
        args,
        operator_lookup,
        max_cost,
        pre_eval_f=pre_eval_f,
    )


class Program(SExp):
    """
    A thin wrapper around s-expression data intended to be invoked with "eval".
    """

    @classmethod
    def parse(cls, f):
        return sexp_from_stream(f, cls.to)

    def stream(self, f):
        sexp_to_stream(self, f)

    @classmethod
    def from_bytes(cls, blob: bytes) -> "Program":
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

    def run_with_cost(self, args) -> Tuple[int, "Program"]:
        prog_args = Program.to(args)
        return run_program(self, prog_args)

    def run(self, args) -> "Program":
        cost, r = self.run_with_cost(args)
        return Program.to(r)

    def curry(self, *args) -> "Program":
        cost, r = curry(self, list(args))
        return Program.to(r)

    def uncurry(self) -> Optional[Tuple["Program", "Program"]]:
        return uncurry(self)

    def as_int(self) -> int:
        return int_from_bytes(self.as_atom())

    def __deepcopy__(self, memo):
        return type(self).from_bytes(bytes(self))

    EvalError = EvalError


def _tree_hash(node: SExp, precalculated: Set[bytes32]) -> bytes32:
    """
    Hash values in `precalculated` are presumed to have been hashed already.
    """
    if node.listp():
        left = _tree_hash(node.first(), precalculated)
        right = _tree_hash(node.rest(), precalculated)
        s = b"\2" + left + right
    else:
        atom = node.as_atom()
        if atom in precalculated:
            return bytes32(atom)
        s = b"\1" + atom
    return bytes32(std_hash(s))


def _serialize(node) -> bytes:
    if type(node) == SerializedProgram:
        return bytes(node)
    else:
        return SExp.to(node).as_bin()


class SerializedProgram:
    """
    An opaque representation of a clvm program. It has a more limited interface than a full SExp
    """

    _buf: bytes = b""

    @classmethod
    def parse(cls, f) -> "SerializedProgram":
        tmp = sexp_buffer_from_stream(f)
        return SerializedProgram.from_bytes(tmp)

    def stream(self, f):
        f.write(self._buf)

    @classmethod
    def from_bytes(cls, blob: bytes) -> "SerializedProgram":
        ret = SerializedProgram()
        ret._buf = bytes(blob)
        return ret

    def __bytes__(self) -> bytes:
        return self._buf

    def __str__(self) -> str:
        return bytes(self).hex()

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, str(self))

    def __eq__(self, other) -> bool:
        if not isinstance(other, SerializedProgram):
            return False
        return self._buf == other._buf

    def __ne__(self, other) -> bool:
        if not isinstance(other, SerializedProgram):
            return True
        return self._buf != other._buf

    def get_tree_hash(self, *args: List[bytes32]) -> bytes32:
        """
        Any values in `args` that appear in the tree
        are presumed to have been hashed already.
        """
        tmp = sexp_from_stream(io.BytesIO(self._buf), SExp.to)
        return _tree_hash(tmp, set(args))

    def run_safe_with_cost(self, *args) -> Tuple[int, SExp]:
        return self._run(STRICT_MODE, *args)

    def run_with_cost(self, *args) -> Tuple[int, SExp]:
        return self._run(0, *args)

    def _run(self, flags, *args) -> Tuple[int, SExp]:
        # when multiple arguments are passed, concatenate them into a serialized
        # buffer. Some arguments may already be in serialized form (e.g.
        # SerializedProgram) so we don't want to de-serialize those just to
        # serialize them back again. This is handled by _serialize()
        serialized_args = b""
        if len(args) > 1:
            # when we have more than one argument, serialize them into a list
            for a in args:
                serialized_args += b"\xff"
                serialized_args += _serialize(a)
            serialized_args += b"\x80"
        else:
            serialized_args += _serialize(args[0])

        max_cost = 0
        # TODO: move this ugly magic into `clvm` "dialects"
        native_opcode_names_by_opcode = dict(
            ("op_%s" % OP_REWRITE.get(k, k), op) for op, k in KEYWORD_FROM_ATOM.items() if k not in "qa."
        )
        cost, ret = deserialize_and_run_program(
            self._buf,
            serialized_args,
            KEYWORD_TO_ATOM["q"][0],
            KEYWORD_TO_ATOM["a"][0],
            native_opcode_names_by_opcode,
            max_cost,
            flags,
        )
        # TODO this could be parsed lazily
        return cost, sexp_from_stream(io.BytesIO(ret), SExp.to)
