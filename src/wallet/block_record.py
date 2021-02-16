from dataclasses import dataclass
from typing import List

from src.types.blockchain_format.coin import Coin
from src.types.header_block import HeaderBlock
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class HeaderBlockRecord(Streamable):
    """
    These are values that are stored in the wallet database, corresponding to information
    that the wallet cares about in each block
    """

    header: HeaderBlock
    additions: List[Coin]  # A block record without additions is not finished
    removals: List[Coin]  # A block record without removals is not finished

    @property
    def header_hash(self):
        return self.header.header_hash

    @property
    def prev_header_hash(self):
        return self.header.prev_header_hash

    @property
    def height(self):
        return self.header.height

    @property
    def transactions_filter(self):
        return self.header.transactions_filter
