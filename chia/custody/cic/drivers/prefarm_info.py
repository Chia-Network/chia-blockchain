from dataclasses import dataclass

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class PrefarmInfo(Streamable):
    launcher_id: bytes32
    puzzle_root: bytes32
    withdrawal_timelock: uint64
    payment_clawback_period: uint64
    rekey_clawback_period: uint64
    rekey_increments: uint64
    slow_rekey_timelock: uint64

    def is_valid_update(self, new: "PrefarmInfo") -> bool:
        return (
            self.launcher_id,
            self.withdrawal_timelock,
            self.payment_clawback_period,
            self.rekey_clawback_period,
        ) == (
            new.launcher_id,
            new.withdrawal_timelock,
            new.payment_clawback_period,
            new.rekey_clawback_period,
        )
