from __future__ import annotations

from chia_puzzles_py.programs import NOTIFICATION
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.program import Program

NOTIFICATION_MOD = Program.from_bytes(NOTIFICATION)


def construct_notification(target: bytes32, amount: uint64) -> Program:
    return NOTIFICATION_MOD.curry(target, amount)
