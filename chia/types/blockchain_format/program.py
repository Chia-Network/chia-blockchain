from __future__ import annotations

import io
from typing import Any, BinaryIO, Callable, Dict, Generator, Optional, Set, Tuple

from chia_rs import ALLOW_BACKREFS, run_chia_program, tree_hash
from clvm import SExp
from clvm.casts import int_from_bytes
from clvm.EvalError import EvalError
from clvm.serialize import sexp_from_stream, sexp_to_stream
from clvm.SExp import CastableType

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash

from .tree_hash import sha256_treehash

INFINITE_COST = 11000000000


class Program:
    """
    A thin wrapper around s-expression data intended to be invoked with "eval".
    """

    _inner: SExp

    def __init__(self, inner: SExp):
        self._inner = inner

    def as_pair(self) -> Optional[Tuple[Program, Program]]:
        pair: Optional[Tuple[SExp, SExp]] = self._inner.as_pair()
        if pair is None:
            return None
        return (Program(pair[0]), Program(pair[1]))

    def first(self) -> Program:
        return Program(self._inner.first())

    def rest(self) -> Program:
        return Program(self._inner.rest())

    def as_iter(self) -> Generator[Program, None, None]:
        v = self._inner
        while not v.nullp():
            yield Program(v.first())
            v = v.rest()

    def listp(self) -> bool:
        ret: bool = self._inner.listp()
        return ret

    def nullp(self) -> bool:
        ret: bool = self._inner.nullp()
        return ret

    def cons(self, right: CastableType) -> Program:
        return Program.to((self._inner, Program.to(right)))

    def __eq__(self, other: CastableType) -> bool:
        ret: bool = self._inner == other
        return ret

    def list_len(self) -> int:
        ret: int = self._inner.list_len()
        return ret

    def as_bin(self) -> bytes:
        ret: bytes = self._inner.as_bin()
        return ret

    def as_python(self) -> Any:
        return self._inner.as_python()

    @property
    def atom(self) -> Optional[bytes]:
        ret: Optional[bytes] = self._inner.atom
        return ret

    @property
    def pair(self) -> Optional[Tuple[Program, Program]]:
        pair: Optional[Tuple[SExp, SExp]] = self._inner.as_pair()
        if pair is None:
            return None
        return (Program(pair[0]), Program(pair[1]))

    @staticmethod
    def to(v: CastableType) -> Program:
        if isinstance(v, Program):
            return v
        return Program(SExp.to(v))

    @staticmethod
    def parse(f: BinaryIO) -> Program:
        return Program(sexp_from_stream(f, Program.to))

    def stream(self, f: io.BytesIO) -> None:
        sexp_to_stream(self._inner, f)

    @staticmethod
    def from_bytes(blob: bytes) -> Program:
        # this runs the program "1", which just returns the first argument.
        # the first argument is the buffer we want to parse. This effectively
        # leverages the rust parser and LazyNode, making it a lot faster to
        # parse serialized programs into a python compatible structure
        cost, ret = run_chia_program(
            b"\x01",
            blob,
            50,
            ALLOW_BACKREFS,
        )
        return Program.to(ret)

    @staticmethod
    def fromhex(hexstr: str) -> Program:
        return Program.from_bytes(hexstr_to_bytes(hexstr))

    def __bytes__(self) -> bytes:
        f = io.BytesIO()
        self.stream(f)  # noqa
        return f.getvalue()

    def __str__(self) -> str:
        return self.as_bin().hex()

    def __repr__(self) -> str:
        return f"Program({self})"

    def at(self, position: str) -> Program:
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

    def replace(self, **kwargs: CastableType) -> Program:
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
        return Program(_sexp_replace(self, self.to, **kwargs))

    def get_tree_hash_precalc(self, *args: bytes32) -> bytes32:
        """
        Any values in `args` that appear in the tree
        are presumed to have been hashed already.
        """
        return sha256_treehash(self._inner, set(args))

    def get_tree_hash(self) -> bytes32:
        return bytes32(tree_hash(bytes(self)))

    def _run(self, max_cost: int, flags: int, args: object) -> Tuple[int, Program]:
        prog_args = Program.to(args)
        cost, r = run_chia_program(self.as_bin(), prog_args.as_bin(), max_cost, flags)
        return cost, Program.to(r)

    def run_with_cost(self, max_cost: int, args: object) -> Tuple[int, Program]:
        return self._run(max_cost, 0, args)

    def run(self, args: object) -> Program:
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
    def curry(self, *args: CastableType) -> Program:
        fixed_args: CastableType = 1
        for arg in reversed(args):
            fixed_args = [4, (1, arg), fixed_args]
        return Program.to([2, (1, self._inner), fixed_args])

    def uncurry(self) -> Tuple[Program, Program]:
        def match(o: SExp, expected: bytes) -> None:
            if o.atom != expected:
                raise ValueError(f"expected: {expected.hex()}")

        try:
            # (2 (1 . <mod>) <args>)
            ev, quoted_inner, args_list = self.as_iter()
            match(ev, b"\x02")
            pair = quoted_inner.pair
            if pair is None:
                raise ValueError("expected pair for quoted inner function")
            match(pair[0], b"\x01")
            mod = pair[1]
            args = []
            while args_list.pair is not None:
                # (4 (1 . <arg>) <rest>)
                cons, quoted_arg, rest = args_list.as_iter()
                match(cons, b"\x04")
                pair = quoted_arg.pair
                if pair is None:
                    raise ValueError("expected pair for quoted inner function")
                match(pair[0], b"\x01")
                args.append(pair[1])
                args_list = rest
            match(args_list, b"\x01")
            return Program.to(mod), Program.to(args)
        except ValueError:  # too many values to unpack
            # when unpacking as_iter()
            # or when a match() fails
            return self, Program.to(0)
        except TypeError:  # NoneType not subscriptable
            # when an object is not a pair or atom as expected
            return self, Program.to(0)
        except EvalError:  # first of non-cons
            # when as_iter() fails
            return self, Program.to(0)

    def as_int(self) -> int:
        ret: int = int_from_bytes(self.as_atom())
        return ret

    def as_atom(self) -> bytes:
        ret: Optional[bytes] = self.atom
        if ret is None:
            raise ValueError("expected atom")
        return ret

    def __deepcopy__(self) -> Program:
        return Program.from_bytes(bytes(self))

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


NIL = Program.from_bytes(b"\x80")


def _sexp_replace(sexp: SExp, to_sexp: Callable[[CastableType], SExp], **kwargs: Dict[str, CastableType]) -> SExp:
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
