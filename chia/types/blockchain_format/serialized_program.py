from __future__ import annotations

import io
from typing import Tuple, Type

from chia_rs import MEMPOOL_MODE, run_chia_program, serialized_length, tree_hash
from clvm import SExp

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes


def _serialize(node: object) -> bytes:
    if isinstance(node, list):
        serialized_list = bytearray()
        for a in node:
            serialized_list += b"\xff"
            serialized_list += _serialize(a)
        serialized_list += b"\x80"
        return bytes(serialized_list)
    if type(node) is SerializedProgram:
        return bytes(node)
    if type(node) is Program:
        return bytes(node)
    else:
        ret: bytes = SExp.to(node).as_bin()
        return ret


class SerializedProgram:
    """
    An opaque representation of a clvm program. It has a more limited interface than a full SExp
    """

    _buf: bytes = b""

    @classmethod
    def parse(cls: Type[SerializedProgram], f: io.BytesIO) -> SerializedProgram:
        length = serialized_length(f.getvalue()[f.tell() :])
        return SerializedProgram.from_bytes(f.read(length))

    def stream(self, f: io.BytesIO) -> None:
        f.write(self._buf)

    @classmethod
    def from_bytes(cls: Type[SerializedProgram], blob: bytes) -> SerializedProgram:
        ret = SerializedProgram()
        assert serialized_length(blob) == len(blob)
        ret._buf = bytes(blob)
        return ret

    @classmethod
    def fromhex(cls: Type[SerializedProgram], hexstr: str) -> SerializedProgram:
        return cls.from_bytes(hexstr_to_bytes(hexstr))

    @classmethod
    def from_program(cls: Type[SerializedProgram], p: Program) -> SerializedProgram:
        ret = SerializedProgram()
        ret._buf = bytes(p)
        return ret

    def to_program(self) -> Program:
        return Program.from_bytes(self._buf)

    def uncurry(self) -> Tuple[Program, Program]:
        return self.to_program().uncurry()

    def __bytes__(self) -> bytes:
        return self._buf

    def __str__(self) -> str:
        return bytes(self).hex()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({str(self)})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SerializedProgram):
            return False
        return self._buf == other._buf

    def __ne__(self, other: object) -> bool:
        if not isinstance(other, SerializedProgram):
            return True
        return self._buf != other._buf

    def get_tree_hash(self) -> bytes32:
        return bytes32(tree_hash(self._buf))

    def run_mempool_with_cost(self, max_cost: int, arg: object) -> Tuple[int, Program]:
        return self._run(max_cost, MEMPOOL_MODE, arg)

    def run_with_cost(self, max_cost: int, arg: object) -> Tuple[int, Program]:
        return self._run(max_cost, 0, arg)

    def _run(self, max_cost: int, flags: int, arg: object) -> Tuple[int, Program]:
        # when multiple arguments are passed, concatenate them into a serialized
        # buffer. Some arguments may already be in serialized form (e.g.
        # SerializedProgram) so we don't want to de-serialize those just to
        # serialize them back again. This is handled by _serialize()
        serialized_args = _serialize(arg)

        cost, ret = run_chia_program(
            self._buf,
            bytes(serialized_args),
            max_cost,
            flags,
        )
        return cost, Program.to(ret)
