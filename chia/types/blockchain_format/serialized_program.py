from __future__ import annotations

from typing import Tuple, Type

from chia_rs import MEMPOOL_MODE, run_chia_program

from clvm_rs import Program as RSProgram

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes


class SerializedProgram(RSProgram):
    """
    An opaque representation of a clvm program. It has a more limited interface than a full SExp
    """

    @property
    def _buf(self):
        return bytes(self)

    @staticmethod
    def fromhex(hexstr: str) -> SerializedProgram:
        return SerializedProgram.from_bytes(hexstr_to_bytes(hexstr))

    @classmethod
    def from_program(cls: Type[SerializedProgram], p: Program) -> SerializedProgram:
        return cls.to(p)

    def to_program(self) -> Program:
        return Program.to(self)

    def uncurry(self) -> Tuple[Program, Program]:
        return self.to_program().uncurry()

    def __str__(self) -> str:
        return bytes(self).hex()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({str(self)})"

    def get_tree_hash(self) -> bytes32:
        return bytes32(self.tree_hash())

    def run_mempool_with_cost(self, max_cost: int, arg: object) -> Tuple[int, Program]:
        return self._run(max_cost, MEMPOOL_MODE, arg)

    def run_with_cost(self, max_cost: int, arg: object) -> Tuple[int, Program]:
        return self._run(max_cost, 0, arg)

    def _run(self, max_cost: int, flags: int, arg: object) -> Tuple[int, Program]:
        # when multiple arguments are passed, concatenate them into a serialized
        # buffer. Some arguments may already be in serialized form (e.g.
        # SerializedProgram) so we don't want to de-serialize those just to
        # serialize them back again. This is handled by _serialize()
        serialized_args = self.to(arg)

        cost, ret = run_chia_program(
            self._buf,
            bytes(serialized_args),
            max_cost,
            flags,
        )
        return cost, Program.to(ret)
