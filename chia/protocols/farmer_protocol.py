from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from blspy import G2Element

from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable

"""
Protocol between farmer and full node.
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


@streamable
@dataclass(frozen=True)
class NewSignagePoint(Streamable):
    challenge_hash: bytes32
    challenge_chain_sp: bytes32
    reward_chain_sp: bytes32
    difficulty: uint64
    sub_slot_iters: uint64
    signage_point_index: uint8
    peak_height: uint32


@streamable
@dataclass(frozen=True)
class DeclareProofOfSpace(Streamable):
    challenge_hash: bytes32
    challenge_chain_sp: bytes32
    signage_point_index: uint8
    reward_chain_sp: bytes32
    proof_of_space: ProofOfSpace
    challenge_chain_sp_signature: G2Element
    reward_chain_sp_signature: G2Element
    farmer_puzzle_hash: bytes32
    pool_target: Optional[PoolTarget]
    pool_signature: Optional[G2Element]


@streamable
@dataclass(frozen=True)
class RequestSignedValues(Streamable):
    quality_string: bytes32
    foliage_block_data_hash: bytes32
    foliage_transaction_block_hash: bytes32


@streamable
@dataclass(frozen=True)
class FarmingInfo(Streamable):
    challenge_hash: bytes32
    sp_hash: bytes32
    timestamp: uint64
    passed: uint32
    proofs: uint32
    total_plots: uint32


@streamable
@dataclass(frozen=True)
class SignedValues(Streamable):
    quality_string: bytes32
    foliage_block_data_signature: G2Element
    foliage_transaction_block_signature: G2Element
