from dataclasses import dataclass
from typing import List, Optional, Tuple

from chives.types.blockchain_format.coin import Coin
from chives.types.blockchain_format.sized_bytes import bytes32
from chives.types.spend_bundle import SpendBundle
from chives.util.ints import uint8, uint32, uint64
from chives.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class TradeRecord(Streamable):
    """
    Used for storing transaction data and status in wallets.
    """

    confirmed_at_index: uint32
    accepted_at_time: Optional[uint64]
    created_at_time: uint64
    my_offer: bool
    sent: uint32
    spend_bundle: SpendBundle  # This in not complete spendbundle
    tx_spend_bundle: Optional[SpendBundle]  # this is full trade
    additions: List[Coin]
    removals: List[Coin]
    trade_id: bytes32
    status: uint32  # TradeStatus, enum not streamable
    sent_to: List[Tuple[str, uint8, Optional[str]]]
