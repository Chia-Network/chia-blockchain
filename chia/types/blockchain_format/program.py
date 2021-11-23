import io
from typing import List, Set, Tuple, Optional, Any

from clvm import KEYWORD_FROM_ATOM, KEYWORD_TO_ATOM, SExp
from clvm import run_program as default_run_program
from clvm.casts import int_from_bytes
from clvm.EvalError import EvalError
from clvm.operators import OP_REWRITE, OPERATOR_LOOKUP
from clvm.serialize import sexp_from_stream, sexp_to_stream
from clvm_rs import STRICT_MODE, deserialize_and_run_program2, serialized_length, run_generator
from clvm_tools.curry import curry, uncurry

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.byte_types import hexstr_to_bytes

from .tree_hash import sha256_treehash


def run_program(
    program,
    args,
    max_cost,
    operator_lookup=OPERATOR_LOOKUP,
    pre_eval_f=None,
):
    return default_run_program(
        program,
        args,
        operator_lookup,
        max_cost,
        pre_eval_f=pre_eval_f,
    )


INFINITE_COST = 0x7FFFFFFFFFFFFFFF


class Program(SExp):
    """
    A thin wrapper around s-expression data intended to be invoked with "eval".
    """

    @classmethod
    def parse(cls, f) -> "Program":
        return sexp_from_stream(f, cls.to)

    def stream(self, f):
        sexp_to_stream(self, f)

    @classmethod
    def from_bytes(cls, blob: bytes) -> "Program":
        f = io.BytesIO(blob)
        result = cls.parse(f)  # noqa
        assert f.read() == b""
        return result

    @classmethod
    def fromhex(cls, hexstr: str) -> "Program":
        return cls.from_bytes(hexstr_to_bytes(hexstr))

    def to_serialized_program(self) -> "SerializedProgram":
        return SerializedProgram.from_bytes(bytes(self))

    @classmethod
    def from_serialized_program(cls, sp: "SerializedProgram") -> "Program":
        return cls.from_bytes(bytes(sp))

    def __bytes__(self) -> bytes:
        f = io.BytesIO()
        self.stream(f)  # noqa
        return f.getvalue()

    def __str__(self) -> str:
        return bytes(self).hex()

    def at(self, position: str) -> "Program":
        """
        Take a string of only `f` and `r` characters and follow the corresponding path.

        Example:

        `assert Program.to(17) == Program.to([10, 20, 30, [15, 17], 40, 50]).at("rrrfrf")`

        """
        v = self
        for c in position.lower():
            if c == "f":
                v = v.first()
            elif c == "r":
                v = v.rest()
            else:
                raise ValueError(f"`at` got illegal character `{c}`. Only `f` & `r` allowed")
        return v

    def get_tree_hash(self, *args: bytes32) -> bytes32:
        """
        Any values in `args` that appear in the tree
        are presumed to have been hashed already.
        """
        return sha256_treehash(self, set(args))

    def run_with_cost(self, max_cost: int, args) -> Tuple[int, "Program"]:
        prog_args = Program.to(args)
        cost, r = run_program(self, prog_args, max_cost)
        return cost, Program.to(r)

    def run(self, args) -> "Program":
        cost, r = self.run_with_cost(INFINITE_COST, args)
        return r

    def curry(self, *args) -> "Program":
        cost, r = curry(self, list(args))
        return Program.to(r)

    def uncurry(self) -> Tuple["Program", "Program"]:
        r = uncurry(self)
        if r is None:
            return self, self.to(0)
        return r

    def as_int(self) -> int:
        return int_from_bytes(self.as_atom())

    def as_atom_list(self) -> List[bytes]:
        """
        Pretend `self` is a list of atoms. Return the corresponding
        python list of atoms.

        At each step, we always assume a node to be an atom or a pair.
        If the assumption is wrong, we exit early. This way we never fail
        and always return SOMETHING.
        """
        items = []
        obj = self
        while True:
            pair = obj.pair
            if pair is None:
                break
            atom = pair[0].atom
            if atom is None:
                break
            items.append(atom)
            obj = pair[1]
        return items

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
        length = serialized_length(f.getvalue()[f.tell() :])
        return SerializedProgram.from_bytes(f.read(length))

    def stream(self, f):
        f.write(self._buf)

    @classmethod
    def from_bytes(cls, blob: bytes) -> "SerializedProgram":
        ret = SerializedProgram()
        ret._buf = bytes(blob)
        return ret

    @classmethod
    def fromhex(cls, hexstr: str) -> "SerializedProgram":
        return cls.from_bytes(hexstr_to_bytes(hexstr))

    @classmethod
    def from_program(cls, p: Program) -> "SerializedProgram":
        ret = SerializedProgram()
        ret._buf = bytes(p)
        return ret

    def to_program(self) -> Program:
        return Program.from_bytes(self._buf)

    def uncurry(self) -> Tuple["Program", "Program"]:
        return self.to_program().uncurry()

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

    def get_tree_hash(self, *args: bytes32) -> bytes32:
        """
        Any values in `args` that appear in the tree
        are presumed to have been hashed already.
        """
        tmp = sexp_from_stream(io.BytesIO(self._buf), SExp.to)
        return _tree_hash(tmp, set(args))

    def run_safe_with_cost(self, max_cost: int, *args) -> Tuple[int, Program]:
        return self._run(max_cost, STRICT_MODE, *args)

    def run_with_cost(self, max_cost: int, *args) -> Tuple[int, Program]:
        return self._run(max_cost, 0, *args)

    def run_as_generator(self, max_cost: int, flags: int, *args) -> Tuple[Optional[int], List[Any], int]:
        serialized_args = b""
        if len(args) > 1:
            # when we have more than one argument, serialize them into a list
            for a in args:
                serialized_args += b"\xff"
                serialized_args += _serialize(a)
            serialized_args += b"\x80"
        else:
            serialized_args += _serialize(args[0])

        native_opcode_names_by_opcode = dict(
            ("op_%s" % OP_REWRITE.get(k, k), op) for op, k in KEYWORD_FROM_ATOM.items() if k not in "qa."
        )
        err, npc_list, cost = run_generator(
            self._buf,
            serialized_args,
            KEYWORD_TO_ATOM["q"][0],
            KEYWORD_TO_ATOM["a"][0],
            native_opcode_names_by_opcode,
            max_cost,
            flags,
        )
        return None if err == 0 else err, npc_list, cost

    def _run(self, max_cost: int, flags, *args) -> Tuple[int, Program]:
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

        # TODO: move this ugly magic into `clvm` "dialects"
        native_opcode_names_by_opcode = dict(
            ("op_%s" % OP_REWRITE.get(k, k), op) for op, k in KEYWORD_FROM_ATOM.items() if k not in "qa."
        )
        cost, ret = deserialize_and_run_program2(
            self._buf,
            serialized_args,
            KEYWORD_TO_ATOM["q"][0],
            KEYWORD_TO_ATOM["a"][0],
            native_opcode_names_by_opcode,
            max_cost,
            flags,
        )
        return cost, Program.to(ret)


NIL = Program.from_bytes(b"\x80")
