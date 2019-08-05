from typing import Optional, List
from blspy import PublicKey, PrependSignature
from src.util.cbor_message import cbor_message
from src.util.streamable import streamable
from src.util.ints import uint32, uint64
from src.types.coinbase import CoinbaseInfo
from src.types.challenge import Challenge
from src.types.proof_of_space import ProofOfSpace

"""
Protocol between farmer and pool.
"""


@streamable
class SignedCoinbase:
    coinbase: CoinbaseInfo
    coinbase_signature: PrependSignature


@cbor_message(tag=5000)
class RequestData:
    min_height: Optional[uint32]
    farmer_id: Optional[str]


@cbor_message(tag=5001)
class RespondData:
    posting_url: str
    pool_pubkey: PublicKey
    partials_threshold: uint64
    coinbase_info: List[SignedCoinbase]


@cbor_message(tag=5002)
class Partial:
    challenge: Challenge
    proof_of_space: ProofOfSpace
    farmer_target: str
    # Signature of the challenge + farmer target hash
    signature: PrependSignature


@cbor_message(tag=5003)
class Ack:
    pass
