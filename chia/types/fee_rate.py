from dataclasses import dataclass

from chia.util.ints import uint64


@dataclass
class FeeRate:
    """Fee Rate in mojos / CLVM Cost"""

    mojos_per_clvm_cost: uint64
