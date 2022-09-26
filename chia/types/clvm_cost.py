from dataclasses import dataclass

from chia.util.ints import uint64


@dataclass
class CLVMCost:
    """
    CLVM Cost is the cost to run a CLVM program on the CLVM.
    It is similar to transaction bytes in the Bitcoin, but some operations
    are charged a higher rate, depending on their arguments.
    """
    clvm_cost: uint64
