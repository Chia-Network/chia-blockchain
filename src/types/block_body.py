from blspy import PrependSignature, Signature
from src.util.streamable import streamable
from src.types.sized_bytes import bytes32
from src.types.coinbase import CoinbaseInfo
from src.types.fee_target import FeesTarget
from typing import List


@streamable
class BlockBody:
    coinbase_info: CoinbaseInfo
    coinbase_signature: PrependSignature
    fees_target_info: FeesTarget
    solutions_generator: List[bytes32]  # TODO: use actual transactions
    aggregated_signature: Signature
