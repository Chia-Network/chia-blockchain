from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict

from src.types.coin import Coin
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable
from src.util.ints import uint32, uint64, uint8
from src.wallet.trading.trade_status import TradeStatus


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
    spend_bundle: SpendBundle
    additions: List[Coin]
    removals: List[Coin]
    trade_id: bytes32
    status: uint32  # TradeStatus, enum not streamable
    sent_to: List[Tuple[str, uint8, Optional[str]]]

    def to_ui_dict(self) -> Dict:
        """ Convinence function to return only part of trade record we care about and show correct status to the ui"""
        result = {}
        result["trade_id"] = self.trade_id.hex()
        result["sent"] = self.sent
        result["my_offer"] = self.my_offer
        result["created_at_time"] = self.created_at_time
        result["accepted_at_time"] = self.accepted_at_time
        result["confirmed_at_index"] = self.confirmed_at_index
        result["status"] = TradeStatus(self.status).name
        return result
