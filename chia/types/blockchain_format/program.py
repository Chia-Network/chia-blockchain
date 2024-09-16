from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Set, Tuple, Type, TypeVar

from chia_rs import (
    ALLOW_BACKREFS,
    DISALLOW_INFINITY_G1,
    ENABLE_BLS_OPS_OUTSIDE_GUARD,
    ENABLE_FIXED_DIV,
    MEMPOOL_MODE,
    run_chia_program,
    tree_hash,
)
from clvm.casts import int_from_bytes
from clvm.CLVMObject import CLVMStorage
from clvm.EvalError import EvalError
from clvm.serialize import sexp_from_stream, sexp_to_stream
from clvm.SExp import SExp

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash

from .tree_hash import sha256_treehash

INFINITE_COST = 11000000000

DEFAULT_FLAGS = ENABLE_BLS_OPS_OUTSIDE_GUARD | ENABLE_FIXED_DIV | DISALLOW_INFINITY_G1 | MEMPOOL_MODE

T_CLVMStorage = TypeVar("T_CLVMStorage", bound=CLVMStorage)
T_Program = TypeVar("T_Program", bound="Program")


class Program(SExp):
    """
    A thin wrapper around s-expression data intended to be invoked with "eval".
    """

    @classmethod
    def parse(cls: Type[T_Program], f) -> T_Program:
        return sexp_from_stream(f, cls.to)

    def stream(self, f):
        sexp_to_stream(self, f)

    @classmethod
    def from_bytes(cls: Type[T_Program], blob: bytes) -> T_Program:
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
        return cls.to(ret)

    @classmethod
    def fromhex(cls: Type[T_Program], hexstr: str) -> T_Program:
        return cls.from_bytes(hexstr_to_bytes(hexstr))

    @classmethod
    def from_json_dict(cls: Type[Program], json_dict: Any) -> Program:
        if isinstance(json_dict, cls):
            return json_dict
        item = hexstr_to_bytes(json_dict)
        return cls.from_bytes(item)

    def to_json_dict(self) -> str:
        return f"0x{self}"

    def __bytes__(self) -> bytes:
        f = io.BytesIO()
        self.stream(f)  # noqa
        return f.getvalue()

    def __str__(self) -> str:
        return bytes(self).hex()

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

    def replace(self: T_Program, **kwargs: Any) -> T_Program:
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

    def _run(self, max_cost: int, flags: int, args: Any) -> Tuple[int, Program]:
        prog_args = Program.to(args)
        cost, r = run_chia_program(self.as_bin(), prog_args.as_bin(), max_cost, flags)
        return cost, Program.to(r)

    def run_with_cost(self, max_cost: int, args: Any, flags=DEFAULT_FLAGS) -> Tuple[int, Program]:
        # when running puzzles in the wallet, default to enabling all soft-forks
        # as well as enabling mempool-mode (i.e. strict mode)
        return self._run(max_cost, flags, args)

    def run(self, args: Any, max_cost=INFINITE_COST, flags=DEFAULT_FLAGS) -> Program:
        cost, r = self._run(max_cost, flags, args)
        return r

    def run_with_flags(self, max_cost: int, flags: int, args: Any) -> Tuple[int, Program]:
        return self._run(max_cost, flags, args)

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
    def curry(self, *args) -> Program:
        fixed_args: Any = 1
        for arg in reversed(args):
            fixed_args = [4, (1, arg), fixed_args]
        return Program.to([2, (1, self), fixed_args])

    def uncurry(self) -> Tuple[Program, Program]:
        def match(o: CLVMStorage, expected: bytes) -> None:
            if o.atom != expected:
                raise ValueError(f"expected: {expected.hex()}")

        try:
            # (2 (1 . <mod>) <args>)
            ev, quoted_inner, args_list = self.as_iter()
            match(ev, b"\x02")
            if TYPE_CHECKING:
                # this being False is presently handled in the TypeError exception handler below
                assert quoted_inner.pair is not None
            match(quoted_inner.pair[0], b"\x01")
            mod = quoted_inner.pair[1]
            args = []
            while args_list.pair is not None:
                # (4 (1 . <arg>) <rest>)
                cons, quoted_arg, rest = args_list.as_iter()
                match(cons, b"\x04")
                if TYPE_CHECKING:
                    # this being False is presently handled in the TypeError exception handler below
                    assert quoted_arg.pair is not None
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

    def as_atom(self) -> bytes:
        ret: Optional[bytes] = self.atom
        if ret is None:
            raise ValueError("expected atom")
        return ret

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
        # node.listp() is False so must be an atom
        atom: bytes = node.as_atom()  # type: ignore[assignment]
        if atom in precalculated:
            return bytes32(atom)
        s = b"\1" + atom
    return bytes32(std_hash(s))


NIL = Program.from_bytes(b"\x80")


# real return type is more like Union[T_Program, CastableType] when considering corner and terminal cases
def _sexp_replace(sexp: T_CLVMStorage, to_sexp: Callable[[Any], T_Program], **kwargs: Any) -> T_Program:
    # if `kwargs == {}` then `return sexp` unchanged
    if len(kwargs) == 0:
        # yes, the terminal case is hinted incorrectly for now
        return sexp  # type: ignore[return-value]

    if "" in kwargs:
        if len(kwargs) > 1:
            raise ValueError("conflicting paths")
        return kwargs[""]

    # we've confirmed that no `kwargs` is the empty string.
    # Now split `kwargs` into two groups: those
    # that start with `f` and those that start with `r`

    args_by_prefix: Dict[str, Dict[str, Any]] = {}
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
