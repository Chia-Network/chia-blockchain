from __future__ import annotations

from dataclasses import dataclass

import typing_extensions

from chia.types.clvm_cost import CLVMCost
from chia.types.mojos import Mojos
from chia.util.streamable import Streamable, streamable


@typing_extensions.final
@streamable
@dataclass(frozen=True)
class WalletFeeRate(Streamable):
    """
    Represents Fee Rate in mojos divided by CLVM Cost.
    """

    mojos: Mojos
    clvm_cost: CLVMCost

    def get_rate_as_float(self) -> float:
        return float(self.mojos) / float(self.clvm_cost)
