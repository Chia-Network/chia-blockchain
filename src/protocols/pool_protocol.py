from dataclasses import dataclass
from typing import List, Optional

from blspy import PrependSignature, PublicKey

from src.types.challenge import Challenge
from src.types.coinbase import CoinbaseInfo
from src.types.proof_of_space import ProofOfSpace
from src.util.cbor_message import cbor_message
from src.util.ints import uint32, uint64
from src.util.streamable import streamable


"""
Protocol between farmer and pool.
"""


@dataclass(frozen=True)
@streamable
class SignedCoinbase:
    coinbase: CoinbaseInfo
    coinbase_signature: PrependSignature


@dataclass(frozen=True)
@cbor_message
class RequestData:
    min_height: Optional[uint32]
    farmer_id: Optional[str]


@dataclass(frozen=True)
@cbor_message
class RespondData:
    posting_url: str
    pool_pubkey: PublicKey
    partials_threshold: uint64
    coinbase_info: List[SignedCoinbase]


@dataclass(frozen=True)
@cbor_message
class Partial:
    challenge: Challenge
    proof_of_space: ProofOfSpace
    farmer_target: str
    # Signature of the challenge + farmer target hash
    signature: PrependSignature


@dataclass(frozen=True)
@cbor_message
class PartialAck:
    pass
