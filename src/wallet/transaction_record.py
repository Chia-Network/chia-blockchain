from dataclasses import dataclass
from typing import Dict, Optional

from src.types.hashable.Coin import Coin
from src.types.hashable.SpendBundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable
from src.util.ints import uint32, uint64


@dataclass(frozen=True)
@streamable
class TransactionRecord(Streamable):
    """
    Used for storing transaction data and status in wallets
    """

    confirmed_block_index: uint32
    created_at_index: uint32
    confirmed: bool
    sent: bool
    created_at_time: uint64
    spend_bundle: Optional[SpendBundle]
    additions: Dict[bytes32, Coin]
    removals: Dict[bytes32, Coin]

    @property
    def name(self) -> bytes32:
        if self.spend_bundle:
            return self.spend_bundle.name()
        return self.get_hash()
