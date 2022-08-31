from typing import Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.puzzles.load_clvm import load_clvm

NOTIFICATION_LAUNCHER = load_clvm("notification_launcher.clvm")
NOTIFICATION_LAUNCHER_HASH = NOTIFICATION_LAUNCHER.get_tree_hash()
NOTIFICATION_MOD = load_clvm("notification.clvm")
NOTIFICATION_CURRIED = NOTIFICATION_MOD.curry(NOTIFICATION_LAUNCHER_HASH)
NOTIFICATION_HASH = NOTIFICATION_CURRIED.get_tree_hash()


def uncurry_notification_launcher(launcher_puzzle: Program) -> Tuple[bytes32, Program]:
    msg, target = launcher_puzzle.uncurry()[1].as_iter()
    return bytes32(target.as_python()), msg


def construct_notification_launcher(target: bytes32, msg: Program) -> Program:
    return NOTIFICATION_LAUNCHER.curry(msg, target)


def solve_notification_launcher(amount: uint64) -> Program:
    return Program.to([NOTIFICATION_HASH, amount])


def solve_notification(target: bytes32, msg_hash: bytes32, parent_id: bytes32, amount: uint64) -> Program:
    return Program.to([msg_hash, target, [parent_id, amount]])
