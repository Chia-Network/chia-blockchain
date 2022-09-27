import math
from dataclasses import dataclass

from chia.types.clvm_cost import CLVMCost
from chia.types.mojos import Mojos
from chia.util.ints import uint64
from chia.util.streamable import streamable, Streamable


@streamable
@dataclass(frozen=True)
class FeeRate(Streamable):
    """
    Represents Fee Rate in mojos divided by CLVM Cost.
    Performs XCH/mojo conversion.
    Similar to 'Fee per cost'.
    """

    mojos_per_clvm_cost: uint64

    @classmethod
    def create(cls, mojos: Mojos, clvm_cost: CLVMCost):
        return cls(uint64(math.ceil(mojos.mojos/clvm_cost.clvm_cost)))
