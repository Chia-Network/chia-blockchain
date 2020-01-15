from dataclasses import dataclass
from typing import Optional
from src.types.hashable import Program, BLSSignature
from src.types.hashable.Coin import Coin
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class Body(Streamable):
    coinbase: Coin
    coinbase_signature: BLSSignature
    fees_coin: Coin
    transactions: Optional[Program]
    aggregated_signature: Optional[BLSSignature]
    solutions_generator: bytes32  # TODO: use actual transactions
    cost: uint64
