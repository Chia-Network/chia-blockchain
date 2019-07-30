from blspy import PrependSignature, Signature
from src.util.streamable import streamable
from src.types.coinbase import CoinbaseInfo
from src.types.fees_target import FeesTarget


@streamable
class BlockBody:
    coinbase: CoinbaseInfo
    coinbase_signature: PrependSignature
    fees_target_info: FeesTarget
    aggregated_signature: Signature
    solutions_generator: bytes  # TODO: use actual transactions
