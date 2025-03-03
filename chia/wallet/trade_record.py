from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TypeVar

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia.types.blockchain_format.coin import Coin
from chia.util.streamable import Streamable, streamable
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus

_T_TradeRecord = TypeVar("_T_TradeRecord", bound="TradeRecordOld")


@streamable
@dataclass(frozen=True)
class TradeRecordOld(Streamable):
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
    coins_of_interest: list[Coin]
    trade_id: bytes32
    status: uint32  # TradeStatus, enum not streamable
    sent_to: list[tuple[str, uint8, Optional[str]]]  # MempoolSubmissionStatus.status enum not streamable

    def to_json_dict_convenience(self) -> dict[str, Any]:
        formatted = self.to_json_dict()
        formatted["status"] = TradeStatus(self.status).name
        offer_to_summarize: bytes = self.offer if self.taken_offer is None else self.taken_offer
        offer = Offer.from_bytes(offer_to_summarize)
        offered, requested, infos, _ = offer.summary()
        formatted["summary"] = {
            "offered": offered,
            "requested": requested,
            "infos": infos,
            "fees": offer.fees(),
        }
        formatted["pending"] = offer.get_pending_amounts()
        del formatted["offer"]
        return formatted

    @classmethod
    def from_json_dict_convenience(
        cls: type[_T_TradeRecord], record: dict[str, Any], offer: str = ""
    ) -> _T_TradeRecord:
        new_record = record.copy()
        new_record["status"] = TradeStatus[record["status"]].value
        del new_record["summary"]
        del new_record["pending"]
        new_record["offer"] = offer
        return cls.from_json_dict(new_record)


@streamable
@dataclass(frozen=True)
class TradeRecord(TradeRecordOld):
    valid_times: ConditionValidTimes
