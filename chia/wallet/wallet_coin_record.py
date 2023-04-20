from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.ints import uint32, uint64
from chia.util.misc import VersionedBlob
from chia.wallet.util.wallet_types import CoinType, WalletType


@dataclass(frozen=True)
class WalletCoinRecord:
    """
    These are values that correspond to a CoinName that are used
    in keeping track of the unspent database.
    """

    coin: Coin
    confirmed_block_height: uint32
    spent_block_height: uint32
    spent: bool
    coinbase: bool
    wallet_type: WalletType
    wallet_id: int
    # Cannot include new attributes in the hash since they will change the coin order in a set.
    # The launcher coin ID will change and will break all hardcode offer tests in CAT/NFT/DL, etc.
    # TODO Change hardcode offer in unit tests
    coin_type: CoinType = field(default=CoinType.NORMAL, hash=False)
    metadata: Optional[VersionedBlob] = field(default=None, hash=False)

    def name(self) -> bytes32:
        return self.coin.name()

    def to_coin_record(self, timestamp: uint64) -> CoinRecord:
        return CoinRecord(self.coin, self.confirmed_block_height, self.spent_block_height, self.coinbase, timestamp)
