from __future__ import annotations

from dataclasses import dataclass

from chia_rs import CoinState
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.types.blockchain_format.coin import Coin
from chia.util.streamable import Streamable, streamable

from chia_rs import CoinRecord as RustCoinRecord

CoinRecord = RustCoinRecord
