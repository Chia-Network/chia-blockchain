from __future__ import annotations

import io
from typing import Optional, Tuple, Type, Union

from chia_rs import MEMPOOL_MODE, run_chia_program, run_generator, serialized_length, tree_hash
from clvm import SExp

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle_conditions import SpendBundleConditions
from chia.util.byte_types import hexstr_to_bytes


def _serialize(node: object) -> bytes:
    if type(node) == SerializedProgram:
        return bytes(node)
    if type(node) == Program:
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
        return "%s(%s)" % (self.__class__.__name__, str(self))

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

    def run_mempool_with_cost(self, max_cost: int, *args: object) -> Tuple[int, Program]:
        return self._run(max_cost, MEMPOOL_MODE, *args)

    def run_with_cost(self, max_cost: int, *args: object) -> Tuple[int, Program]:
        return self._run(max_cost, 0, *args)

    # returns an optional error code and an optional SpendBundleConditions (from chia_rs)
    # exactly one of those will hold a value
    def run_as_generator(
        self, max_cost: int, flags: int, *args: Union[Program, SerializedProgram]
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

    def _run(self, max_cost: int, flags: int, *args: object) -> Tuple[int, Program]:
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
