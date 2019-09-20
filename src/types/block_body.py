from typing import Optional
from blspy import PrependSignature, Signature
from src.util.streamable import streamable
from src.types.coinbase import CoinbaseInfo
from src.types.fees_target import FeesTarget
from src.types.sized_bytes import bytes32


@streamable
class BlockBody:
    coinbase: CoinbaseInfo
    coinbase_signature: PrependSignature
    fees_target_info: FeesTarget
    aggregated_signature: Optional[Signature]
    solutions_generator: bytes32  # TODO: use actual transactions
