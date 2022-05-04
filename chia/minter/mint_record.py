from dataclasses import dataclass
from typing import List, Optional
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class MintRecord(Streamable):
    confirmed_at_height: uint32
    created_at_time: uint64
    to_puzzle_hash: bytes32
    amount: uint64
    fee_amount: uint64
    confirmed: bool
    spend_bundle: Optional[SpendBundle]
    additions: List[Coin]
    removals: List[Coin]
    wallet_id: uint32
    name: bytes32
    depends_on: bytes32  # bundle id of the spendbundle that this mint depends on (Is descendant)
