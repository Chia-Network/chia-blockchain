from dataclasses import dataclass
from typing import Optional

from blspy import G1Element, G2Element

from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64, uint16
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class PoolInfo(Streamable):
    name: str
    logo_url: str
    minimum_difficulty: uint64
    maximum_difficulty: uint64
    relative_lock_height: uint32
    protocol_version: str
    fee: str
    description: str
    pool_puzzle_hash: bytes32


@dataclass(frozen=True)
@streamable
class PartialPayload(Streamable):
    proof_of_space: ProofOfSpace
    sp_hash: bytes32
    end_of_sub_slot: bool
    difficulty: uint64  # This is the difficulty threshold for this account, assuming SSI = 1024*5
    singleton_genesis: bytes32  # This is what identifies the farmer's account for the pool
    owner_public_key: G1Element  # Current public key specified in the singleton
    singleton_coin_id_hint: bytes32  # Some incarnation of the singleton, the later the better
    rewards_target: bytes  # The farmer can choose where to send the rewards. This can take a few minutes


@dataclass(frozen=True)
@streamable
class SubmitPartial(Streamable):
    payload: PartialPayload
    rewards_and_partial_aggregate_signature: G2Element  # Signature of rewards by singleton key, and partial by plot key


@dataclass(frozen=True)
@streamable
class RespondSubmitPartial(Streamable):
    error_code: uint16
    error_message: Optional[str]
    points_balance: uint64
    difficulty: uint64  # Current difficulty that the pool is using to give credit to this farmer
