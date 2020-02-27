from dataclasses import dataclass
from typing import Optional

from src.types.hashable.BLSSignature import BLSSignature
from src.types.hashable.program import Program
from src.types.hashable.coin import Coin
from src.util.ints import uint64
from src.util.streamable import Streamable, streamable
from src.types.sized_bytes import bytes32


@dataclass(frozen=True)
@streamable
class Body(Streamable):
    coinbase: Coin
    coinbase_signature: BLSSignature
    fees_coin: Coin
    transactions: Optional[Program]
    aggregated_signature: Optional[BLSSignature]
    cost: uint64
    extension_data: bytes32
