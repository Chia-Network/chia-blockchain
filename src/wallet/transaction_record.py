from dataclasses import dataclass
from typing import Optional, List, Tuple

from src.types.coin import Coin
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable
from src.util.ints import uint32, uint64, uint8


@dataclass(frozen=True)
@streamable
class TransactionRecord(Streamable):
    """
    Used for storing transaction data and status in wallets.
    """

    confirmed_at_index: uint32
    created_at_time: uint64
    to_puzzle_hash: bytes32
    amount: uint64
    fee_amount: uint64
    incoming: bool
    confirmed: bool
    sent: uint32
    spend_bundle: Optional[SpendBundle]
    additions: List[Coin]
    removals: List[Coin]
    wallet_id: uint64

    # Represents the list of peers that we sent the transaction to, whether each one
    # included it in the mempool, and what the error message (if any) was
    sent_to: List[Tuple[str, uint8, Optional[str]]]

    def name(self) -> bytes32:
        if self.spend_bundle:
            return self.spend_bundle.name()
        return self.get_hash()
