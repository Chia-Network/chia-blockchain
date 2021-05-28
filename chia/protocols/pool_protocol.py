from dataclasses import dataclass
from typing import Optional

from blspy import G1Element, G2Element

from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64, uint16, uint32
from chia.util.streamable import Streamable, streamable


# GET /get_pool_info
@dataclass(frozen=True)
@streamable
class PoolInfo(Streamable):
    name: str
    logo_url: str
    minimum_difficulty: uint64
    relative_lock_height: uint32
    protocol_version: str
    fee: str
    description: str
    target_puzzle_hash: bytes32


@dataclass(frozen=True)
@streamable
class AuthenticationKeyInfo(Streamable):
    authentication_public_key: G1Element
    authentication_public_key_timestamp: uint64


@dataclass(frozen=True)
@streamable
class PartialPayload(Streamable):
    proof_of_space: ProofOfSpace
    sp_hash: bytes32
    end_of_sub_slot: bool
    suggested_difficulty: uint64  # This is suggested the difficulty threshold for this account
    launcher_id: bytes32  # This is what identifies the farmer's account for the pool
    owner_public_key: G1Element  # Current public key specified in the singleton
    pool_payout_instructions: bytes  # The farmer can choose where to send the rewards. This can take a few minutes
    authentication_key_info: AuthenticationKeyInfo


# POST /submit_partial
@dataclass(frozen=True)
@streamable
class SubmitPartial(Streamable):
    payload: PartialPayload
    auth_key_and_partial_aggregate_signature: G2Element  # Sig of auth key by owner key, and partial by plot key and authentication key


# Response in error case
@dataclass(frozen=True)
@streamable
class RespondSubmitPartialError(Streamable):
    error_code: uint16
    error_message: Optional[str]


# Response in success case
@dataclass(frozen=True)
@streamable
class RespondSubmitPartialSuccess(Streamable):
    points_balance: uint64
    current_difficulty: uint64  # Current difficulty that the pool is using to give credit to this farmer
