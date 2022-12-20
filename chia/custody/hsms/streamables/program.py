import hashlib
import io

from typing import Any, Callable, Dict, Iterable, Tuple

from clvm import run_program, CLVMObject, SExp, EvalError
from clvm.casts import int_from_bytes
from clvm.operators import OPERATOR_LOOKUP, OperatorDict  # noqa
from clvm.serialize import sexp_from_stream, sexp_to_stream

from clvm_tools.curry import curry

from hsms.atoms import bytes32, hexbytes
from hsms.meta import bin_methods


class Program(SExp, bin_methods):
    """
    A thin wrapper around s-expression data intended to be invoked with "eval".
    """

    @classmethod
    def parse(cls, f):
        return sexp_from_stream(f, cls.to)

    def stream(self, f):
        sexp_to_stream(self, f)

    @classmethod
    def from_bytes(cls, blob: bytes) -> Any:
        f = io.BytesIO(blob)
        return cls.parse(f)  # type: ignore # noqa

    def __bytes__(self) -> hexbytes:
        f = io.BytesIO()
        self.stream(f)  # type: ignore # noqa
        return hexbytes(f.getvalue())

    def __hash__(self):
        return bytes(self).__hash__()

    def __str__(self) -> str:
        return bytes(self).hex()

    @classmethod
    def from_clvm(cls, node: CLVMObject) -> "Program":
        return Program(node.pair or node.atom)

    def to_clvm(self) -> CLVMObject:
        return self

    def __int__(self) -> int:
        return int_from_bytes(self.atom)

    def tree_hash(self):
        if self.listp():
            left = self.to(self.first()).tree_hash()
            right = self.to(self.rest()).tree_hash()
            s = b"\2" + left + right
        else:
            atom = self.as_atom()
            s = b"\1" + atom
        return bytes32(hashlib.sha256(s).digest())

    def run_with_cost(
        self,
        args,
        max_cost=None,
        strict=False,
    ) -> Tuple[int, "Program"]:
        operator_lookup = OPERATOR_LOOKUP
        prog_args = Program.to(args)
        if strict:

            def fatal_error(op, arguments):
                raise EvalError("unimplemented operator", arguments.to(op))

            operator_lookup = OperatorDict(
                operator_lookup, unknown_op_handler=fatal_error
            )

        cost, r = run_program(
            self,
            prog_args,
            operator_lookup,
            max_cost,
        )

        return cost, Program.to(r)

    def run(self, args, max_cost=None, strict=False):
        return self.run_with_cost(args, max_cost, strict)[1]

    def at(self, position: str) -> "Program":
        """
        Take a string of only `f` and `r` characters and follow the corresponding path.

        Example:

        `assert Program.to(17) == Program.to([10, 20, 30, [15, 17], 40, 50]).at("rrrfrf")`

        """
        v = self
        for c in position.lower():
            if c == "f":
                v = Program.to(v.pair[0])
            elif c == "r":
                v = Program.to(v.pair[1])
            else:
                raise ValueError(
                    f"`at` got illegal character `{c}`. Only `f` & `r` allowed"
                )
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

    def as_atom_list(self) -> Iterable[hexbytes]:
        """
        Pretend `self` is a list of atoms. Return the corresponding
        python list of atoms.

        At each step, we always assume a node to be an atom or a pair.
        If the assumption is wrong, we exit early. This way we never fail
        and always return SOMETHING.
        """
        obj = self
        while obj.pair:
            first, obj = obj.pair
            atom = first.atom
            if atom is None:
                break
            yield hexbytes(atom)

    def curry(self, *args) -> "Program":
        cost, r = curry(self, list(args))
        return Program.to(r)


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
