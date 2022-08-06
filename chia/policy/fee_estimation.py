from dataclasses import dataclass
from datetime import datetime

from chia.util.ints import uint64


@dataclass(frozen=True)
class FeeMempoolInfo:
    """
    Information from Mempool and MempoolItems needed to estimate fees.

    Attributes:
        current_cost (int):This is the current capacity of the mempool, measured in XCH per CLVM Cost
        max_cost (int): This is the maximum capacity of the mempool, measured in XCH per CLVM Cost

    """

    max_size_in_cost: uint64  # Mempool max allowed CLVM cost total
    minimum_fee_per_cost_to_replace: uint64
    # smallest FPC tx / size ...
    # min_fee_rate_for_inclusion: float  # Fee per CLVM Cost a new Spendbundle must exceed to be accepted
    current_mempool_cost: uint64  # Current sum of CLVM cost of all SpendBundles in mempool (mempool "size")
    time: datetime  # Local time this sample was taken


class FeeBlockInfo:
    """
    Information from Blockchain needed to estimate fees.
    """

    pass


class FeeRate:
    """
    Represents Fee in XCH per CLVM Cost. Performs XCH/mojo conversion
    """

    pass
