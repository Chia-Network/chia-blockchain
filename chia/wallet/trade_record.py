from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus


@dataclass(frozen=True)
@streamable
class TradeRecord(Streamable):
    """
    Used for storing transaction data and status in wallets.
    """

    confirmed_at_index: uint32
    accepted_at_time: Optional[uint64]
    created_at_time: uint64
    is_my_offer: bool
    sent: uint32
    offer: bytes
    taken_offer: Optional[bytes]
    coins_of_interest: List[Coin]
    trade_id: bytes32
    status: uint32  # TradeStatus, enum not streamable
    sent_to: List[Tuple[str, uint8, Optional[str]]]

    def to_json_dict_convenience(self) -> Dict[str, Any]:
        formatted = self.to_json_dict()
        formatted["status"] = TradeStatus(self.status).name
        offer_to_summarize: bytes = self.offer if self.taken_offer is None else self.taken_offer
        offer = Offer.from_bytes(offer_to_summarize)
        offered, requested = offer.summary()
        formatted["summary"] = {
            "offered": offered,
            "requested": requested,
        }
        formatted["pending"] = offer.get_pending_amounts()
        del formatted["offer"]
        return formatted

    @classmethod
    def from_json_dict_convenience(cls, record: Dict[str, Any], offer: str = "") -> "TradeRecord":
        new_record = record.copy()
        new_record["status"] = TradeStatus[record["status"]].value
        del new_record["summary"]
        del new_record["pending"]
        new_record["offer"] = offer
        return cls.from_json_dict(new_record)
