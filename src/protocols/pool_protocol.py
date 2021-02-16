from dataclasses import dataclass
from typing import List, Optional


from src.types.blockchain_format.proof_of_space import ProofOfSpace
from src.util.ints import uint32, uint64
from src.util.streamable import streamable, Streamable

"""
Protocol between farmer and pool.
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


@dataclass(frozen=True)
@streamable
class SignedCoinbase(Streamable):
    pass
    # coinbase_signature: PrependSignature


@dataclass(frozen=True)
@streamable
class RequestData(Streamable):
    min_height: Optional[uint32]
    farmer_id: Optional[str]


@dataclass(frozen=True)
@streamable
class RespondData(Streamable):
    posting_url: str
    # pool_public_key: PublicKey
    partials_threshold: uint64
    coinbase_info: List[SignedCoinbase]


@dataclass(frozen=True)
@streamable
class Partial(Streamable):
    # challenge: Challenge
    proof_of_space: ProofOfSpace
    farmer_target: str
    # Signature of the challenge + farmer target hash
    # signature: PrependSignature


@dataclass(frozen=True)
@streamable
class PartialAck(Streamable):
    pass
