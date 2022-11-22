from __future__ import annotations

import io
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from chia_rs import MEMPOOL_MODE, run_chia_program, run_generator, serialized_length, tree_hash
from clvm import SExp
from clvm.casts import int_from_bytes
from clvm.EvalError import EvalError
from clvm.serialize import sexp_from_stream, sexp_to_stream

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle_conditions import SpendBundleConditions
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash

from .tree_hash import sha256_treehash

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
    def from_bytes(cls, blob: bytes) -> Program:
        # this runs the program "1", which just returns the first argument.
        # the first argument is the buffer we want to parse. This effectively
        # leverages the rust parser and LazyNode, making it a lot faster to
        # parse serialized programs into a python compatible structure
        cost, ret = run_chia_program(
            b"\x01",
            blob,
            50,
            0,
        )
        return Program.to(ret)

    @classmethod
    def fromhex(cls, hexstr: str) -> "Program":
        return cls.from_bytes(hexstr_to_bytes(hexstr))

    def to_serialized_program(self) -> "SerializedProgram":
        return SerializedProgram.from_bytes(bytes(self))

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

    def replace(self, **kwargs) -> "Program":
        """
        Create a new program replacing the given paths (using `at` syntax).
        Example:
        ```
        >>> p1 = Program.to([100, 200, 300])
        >>> print(p1.replace(f=105) == Program.to([105, 200, 300]))
        True
        >>> print(p1.replace(rrf=[301, 302]) == Program.to([100, 200, [301, 302]]))
        True
        >>> print(p1.replace(f=105, rrf=[301, 302]) == Program.to([105, 200, [301, 302]]))
        True
        ```

        This is a convenience method intended for use in the wallet or command-line hacks where
        it would be easier to morph elements of an existing clvm object tree than to rebuild
        one from scratch.

        Note that `Program` objects are immutable. This function returns a new object; the
        original is left as-is.
        """
        return _sexp_replace(self, self.to, **kwargs)

    def get_tree_hash_precalc(self, *args: bytes32) -> bytes32:
        """
        Any values in `args` that appear in the tree
        are presumed to have been hashed already.
        """
        return sha256_treehash(self, set(args))

    def get_tree_hash(self) -> bytes32:
        return bytes32(tree_hash(bytes(self)))

    def run_with_cost(self, max_cost: int, args) -> Tuple[int, "Program"]:
        prog_args = Program.to(args)
        cost, r = run_chia_program(self.as_bin(), prog_args.as_bin(), max_cost, 0)
        return cost, Program.to(r)

    def run(self, args) -> "Program":
        cost, r = self.run_with_cost(INFINITE_COST, args)
        return r

    # Replicates the curry function from clvm_tools, taking advantage of *args
    # being a list.  We iterate through args in reverse building the code to
    # create a clvm list.
    #
    # Given arguments to a function addressable by the '1' reference in clvm
    #
    # fixed_args = 1
    #
    # Each arg is prepended as fixed_args = (c (q . arg) fixed_args)
    #
    # The resulting argument list is interpreted with apply (2)
    #
    # (2 (1 . self) rest)
    #
    # Resulting in a function which places its own arguments after those
    # curried in in the form of a proper list.
    def curry(self, *args) -> "Program":
        fixed_args: Any = 1
        for arg in reversed(args):
            fixed_args = [4, (1, arg), fixed_args]
        return Program.to([2, (1, self), fixed_args])

    def uncurry(self) -> Tuple[Program, Program]:
        def match(o: SExp, expected: bytes) -> None:
            if o.atom != expected:
                raise ValueError(f"expected: {expected.hex()}")

        try:
            # (2 (1 . <mod>) <args>)
            ev, quoted_inner, args_list = self.as_iter()
            match(ev, b"\x02")
            match(quoted_inner.pair[0], b"\x01")
            mod = quoted_inner.pair[1]
            args = []
            while args_list.pair is not None:
                # (4 (1 . <arg>) <rest>)
                cons, quoted_arg, rest = args_list.as_iter()
                match(cons, b"\x04")
                match(quoted_arg.pair[0], b"\x01")
                args.append(quoted_arg.pair[1])
                args_list = rest
            match(args_list, b"\x01")
            return Program.to(mod), Program.to(args)
        except ValueError:  # too many values to unpack
            # when unpacking as_iter()
            # or when a match() fails
            return self, self.to(0)
        except TypeError:  # NoneType not subscriptable
            # when an object is not a pair or atom as expected
            return self, self.to(0)
        except EvalError:  # first of non-cons
            # when as_iter() fails
            return self, self.to(0)

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

    def get_tree_hash(self) -> bytes32:
        return bytes32(tree_hash(self._buf))

    def run_mempool_with_cost(self, max_cost: int, *args) -> Tuple[int, Program]:
        return self._run(max_cost, MEMPOOL_MODE, *args)

    def run_with_cost(self, max_cost: int, *args) -> Tuple[int, Program]:
        return self._run(max_cost, 0, *args)

    # returns an optional error code and an optional SpendBundleConditions (from chia_rs)
    # exactly one of those will hold a value
    def run_as_generator(
        self, max_cost: int, flags: int, *args
    ) -> Tuple[Optional[int], Optional[SpendBundleConditions]]:

        serialized_args = bytearray()
        if len(args) > 1:
            # when we have more than one argument, serialize them into a list
            for a in args:
                serialized_args += b"\xff"
                serialized_args += _serialize(a)
            serialized_args += b"\x80"
        else:
            serialized_args += _serialize(args[0])

        err, ret = run_generator(
            self._buf,
            bytes(serialized_args),
            max_cost,
            flags,
        )
        if err is not None:
            assert err != 0
            return err, None

        assert ret is not None
        return None, ret

    def _run(self, max_cost: int, flags, *args) -> Tuple[int, Program]:
        # when multiple arguments are passed, concatenate them into a serialized
        # buffer. Some arguments may already be in serialized form (e.g.
        # SerializedProgram) so we don't want to de-serialize those just to
        # serialize them back again. This is handled by _serialize()
        serialized_args = bytearray()
        if len(args) > 1:
            # when we have more than one argument, serialize them into a list
            for a in args:
                serialized_args += b"\xff"
                serialized_args += _serialize(a)
            serialized_args += b"\x80"
        else:
            serialized_args += _serialize(args[0])

        cost, ret = run_chia_program(
            self._buf,
            bytes(serialized_args),
            max_cost,
            flags,
        )
        return cost, Program.to(ret)


NIL = Program.from_bytes(b"\x80")


def _sexp_replace(sexp: SExp, to_sexp: Callable[[Any], SExp], **kwargs) -> SExp:
    # if `kwargs == {}` then `return sexp` unchanged
    if len(kwargs) == 0:
        return sexp

    if "" in kwargs:
        if len(kwargs) > 1:
            raise ValueError("conflicting paths")
        return kwargs[""]

    # we've confirmed that no `kwargs` is the empty string.
    # Now split `kwargs` into two groups: those
    # that start with `f` and those that start with `r`

    args_by_prefix: Dict[str, SExp] = {}
    for k, v in kwargs.items():
        c = k[0]
        if c not in "fr":
            raise ValueError("bad path containing %s: must only contain `f` and `r`")
        args_by_prefix.setdefault(c, dict())[k[1:]] = v

    pair = sexp.pair
    if pair is None:
        raise ValueError("path into atom")

    # recurse down the tree
    new_f = _sexp_replace(pair[0], to_sexp, **args_by_prefix.get("f", {}))
    new_r = _sexp_replace(pair[1], to_sexp, **args_by_prefix.get("r", {}))

    return to_sexp((new_f, new_r))
