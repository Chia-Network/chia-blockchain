import math
from dataclasses import dataclass

from chia.types.clvm_cost import CLVMCost
from chia.types.mojos import Mojos
from chia.util.ints import uint64


@dataclass
class FeeRate:
    """
    Represents Fee Rate in mojos divided by CLVM Cost.
    Performs XCH/mojo conversion.
    Similar to 'Fee per cost'.
    """

    mojos_per_clvm_cost: uint64

    def __init__(self, mojos: Mojos, clvm_cost: CLVMCost):
        self.mojos_per_clvm_cost = uint64(math.ceil(mojos.mojos/clvm_cost.clvm_cost))
