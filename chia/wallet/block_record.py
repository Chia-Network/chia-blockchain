from __future__ import annotations

from dataclasses import dataclass
from typing import List

from chia.types.blockchain_format.coin import Coin
from chia.types.header_block import HeaderBlock
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
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
