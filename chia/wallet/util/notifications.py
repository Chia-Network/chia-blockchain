from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.puzzles.load_clvm import load_clvm

NOTIFICATION_MOD = load_clvm("notification.clvm")


def construct_notification(target: bytes32, amount: uint64) -> Program:
    return NOTIFICATION_MOD.curry(target, amount)
