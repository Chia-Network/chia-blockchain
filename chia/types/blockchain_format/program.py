from __future__ import annotations

import io
from typing import Any, Optional, Tuple

from chia_rs import run_chia_program
from clvm_rs import Program as RSProgram
from clvm.EvalError import EvalError

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes

from .tree_hash import sha256_treehash

INFINITE_COST = 11000000000


class Program(RSProgram):
    """
    A thin wrapper around s-expression data intended to be invoked with "eval".
    """

    @classmethod
    def fromhex(cls, hexstr: str) -> Program:
        return cls.from_bytes(hexstr_to_bytes(hexstr))

    @classmethod
    def to(cls, v) -> Program:
        if v is None:
            v = 0
        return super(Program, cls).to(v)

    def __bytes__(self) -> bytes:
        f = io.BytesIO()
        self.stream(f)  # noqa
        return f.getvalue()

    def __str__(self) -> str:
        return bytes(self).hex()

    def get_tree_hash_precalc(self, *args: bytes32) -> bytes32:
        """
        Any values in `args` that appear in the tree
        are presumed to have been hashed already.
        """
        return sha256_treehash(self, set(args))

    def get_tree_hash(self) -> bytes32:
        return self.tree_hash()

    def _run(self, max_cost: int, flags: int, args: object) -> Tuple[int, Program]:
        prog_args = Program.to(args)
        cost, r = run_chia_program(self.as_bin(), prog_args.as_bin(), max_cost, flags)
        return cost, Program.to(r)

    def run_with_cost(self, max_cost: int, args: object) -> Tuple[int, Program]:
        return self._run(max_cost, 0, args)

    def run(self, args: object) -> Program:
        cost, r = self.run_with_cost(INFINITE_COST, args)
        return r

    def uncurry(self) -> Tuple[Program, Program]:
        def match(o: Any, expected: bytes) -> None:
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

    def as_bin(self) -> bytes:
        return bytes(self)

    def as_atom(self) -> Optional[bytes]:
        return self.atom

    def as_atom(self) -> bytes:
        ret: Optional[bytes] = self.atom
        if ret is None:
            raise ValueError("expected atom")
        return ret

    def __deepcopy__(self, memo):
        return type(self).from_bytes(bytes(self))

    EvalError = EvalError


NIL = Program.from_bytes(b"\x80")
