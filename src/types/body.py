from dataclasses import dataclass
from typing import Optional

from blspy import PrependSignature, Signature

from src.types.hashable.Coin import Coin
from src.types.fees_target import FeesTarget
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class Body(Streamable):
    coinbase: Coin
    coinbase_signature: PrependSignature
    fees_target_info: FeesTarget
    aggregated_signature: Optional[Signature]
    solutions_generator: bytes32  # TODO: use actual transactions
    cost: uint64
