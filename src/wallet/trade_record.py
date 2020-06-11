from dataclasses import dataclass
from typing import Optional, List, Tuple

from src.types.coin import Coin
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable
from src.util.ints import uint32, uint64, uint8


@dataclass(frozen=True)
@streamable
class TradeRecord(Streamable):
    """
    Used for storing transaction data and status in wallets.
    """

    confirmed_at_index: uint32
    accepted_at_time: Optional[uint64]
    created_at_time: uint64
    confirmed: bool
    sent: uint32
    spend_bundle: SpendBundle
    additions: List[Coin]
    removals: List[Coin]
    trade_id: bytes32
    sent_to: List[Tuple[str, uint8, Optional[str]]]

    def name(self) -> bytes32:
        return self.spend_bundle.name()


@dataclass(frozen=True)
@streamable
class TradeOffer(Streamable):
    """
    Used for storing offer offer spend_bundle and meta data
    """

    created_at_time: uint64
    spend_bundle: SpendBundle

    def name(self) -> bytes32:
        return self.spend_bundle.name()
