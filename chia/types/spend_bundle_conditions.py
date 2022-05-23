from dataclasses import dataclass
from typing import List, Optional, Tuple

from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable


# the Spend and SpendBundleConditions classes are mirrors of native types, returned by
# run_generator
@streamable
@dataclass(frozen=True)
class Spend(Streamable):
    coin_id: bytes32
    puzzle_hash: bytes32
    height_relative: Optional[uint32]
    seconds_relative: uint64
    create_coin: List[Tuple[bytes32, uint64, Optional[bytes]]]
    agg_sig_me: List[Tuple[bytes48, bytes]]


@streamable
@dataclass(frozen=True)
class SpendBundleConditions(Streamable):
    spends: List[Spend]
    reserve_fee: uint64
    height_absolute: uint32
    seconds_absolute: uint64
    agg_sig_unsafe: List[Tuple[bytes48, bytes]]
    cost: uint64
