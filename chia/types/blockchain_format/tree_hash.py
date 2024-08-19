"""
This is an implementation of `sha256_treehash`, used to calculate
puzzle hashes in clvm.

This implementation goes to great pains to be non-recursive so we don't
have to worry about blowing out the python stack.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Set, Union

from clvm.CLVMObject import CLVMStorage
from clvm.SExp import SExp

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash

ValueType = Union[bytes, CLVMStorage]
ValueStackType = List[ValueType]
Op = Callable[[ValueStackType, "OpStackType", Set[bytes32]], None]
OpStackType = List[Op]


def sha256_treehash(sexp: CLVMStorage, precalculated: Optional[Set[bytes32]] = None) -> bytes32:
    """
    Hash values in `precalculated` are presumed to have been hashed already.
    """

    if precalculated is None:
        precalculated = set()

    def handle_sexp(sexp_stack: ValueStackType, op_stack: OpStackType, precalculated: Set[bytes32]) -> None:
        # just trusting it is right, otherwise we get an attribute error
        sexp: SExp = sexp_stack.pop()  # type: ignore[assignment]
        if sexp.pair:
            p0, p1 = sexp.pair
            sexp_stack.append(p0)
            sexp_stack.append(p1)
            op_stack.append(handle_pair)
            op_stack.append(handle_sexp)
            op_stack.append(roll)
            op_stack.append(handle_sexp)
        else:
            # not a pair, so an atom
            atom: bytes = sexp.atom  # type: ignore[assignment]
            if atom in precalculated:
                r = atom
            else:
                r = std_hash(b"\1" + atom)
            sexp_stack.append(r)

    def handle_pair(sexp_stack: ValueStackType, op_stack: OpStackType, precalculated: Set[bytes32]) -> None:
        # just trusting it is right, otherwise we get a type error
        p0: bytes = sexp_stack.pop()  # type: ignore[assignment]
        p1: bytes = sexp_stack.pop()  # type: ignore[assignment]
        sexp_stack.append(std_hash(b"\2" + p0 + p1))

    def roll(sexp_stack: ValueStackType, op_stack: OpStackType, precalculated: Set[bytes32]) -> None:
        p0 = sexp_stack.pop()
        p1 = sexp_stack.pop()
        sexp_stack.append(p0)
        sexp_stack.append(p1)

    sexp_stack: ValueStackType = [sexp]
    op_stack: List[Op] = [handle_sexp]
    while len(op_stack) > 0:
        op = op_stack.pop()
        op(sexp_stack, op_stack, precalculated)
    # just trusting it is right, otherwise we get some error, probably
    result: bytes = sexp_stack[0]  # type: ignore[assignment]
    return bytes32(result)
