from dataclasses import dataclass
from typing import List

from src.util.streamable import streamable, Streamable
from src.wallet.trade_record import TradeOffer, TradeRecord


@dataclass(frozen=True)
@streamable
class PendingOffers(Streamable):
    trades: List[TradeOffer]


@dataclass(frozen=True)
@streamable
class AcceptedOffers(Streamable):
    trades: List[TradeRecord]
