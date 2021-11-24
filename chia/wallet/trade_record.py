from dataclasses import dataclass
from typing import List, Optional, Tuple

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.trading.offer import Offer


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
    offer: Offer
    coins_of_interest: List[Coin]
    trade_id: bytes32
    status: uint32  # TradeStatus, enum not streamable
    sent_to: List[Tuple[str, uint8, Optional[str]]]
