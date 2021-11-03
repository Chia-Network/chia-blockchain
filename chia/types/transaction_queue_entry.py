from dataclasses import dataclass
from typing import Optional

from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle


@dataclass(frozen=True)
class TransactionQueueEntry:
    transaction: SpendBundle
    transaction_bytes: Optional[bytes]
    spend_name: bytes32
    peer: Optional[WSChiaConnection]
    test: bool

    def __lt__(self, other):
        return self.spend_name < other.spend_name

    def __le__(self, other):
        return self.spend_name <= other.spend_name

    def __gt__(self, other):
        return self.spend_name > other.spend_name

    def __ge__(self, other):
        return self.spend_name >= other.spend_name
