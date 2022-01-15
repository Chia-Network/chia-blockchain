from dataclasses import dataclass
from typing import Optional

from chinilla.server.ws_connection import WSChinillaConnection
from chinilla.types.blockchain_format.sized_bytes import bytes32
from chinilla.types.spend_bundle import SpendBundle


@dataclass(frozen=True)
class TransactionQueueEntry:
    """
    A transaction received from peer. This is put into a queue, and not yet in the mempool.
    """

    transaction: SpendBundle
    transaction_bytes: Optional[bytes]
    spend_name: bytes32
    peer: Optional[WSChinillaConnection]
    test: bool

    def __lt__(self, other):
        return self.spend_name < other.spend_name

    def __le__(self, other):
        return self.spend_name <= other.spend_name

    def __gt__(self, other):
        return self.spend_name > other.spend_name

    def __ge__(self, other):
        return self.spend_name >= other.spend_name
