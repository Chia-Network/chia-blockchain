from dataclasses import dataclass
from typing import List, Optional, Tuple

from blspy import G1Element, G2Element

from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint64
from chia.util.streamable import Streamable, streamable

"""
Protocol between harvester and farmer.
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


@dataclass(frozen=True)
@streamable
class PoolDifficulty(Streamable):
    difficulty: uint64
    sub_slot_iters: uint64
    pool_contract_puzzle_hash: bytes32


@dataclass(frozen=True)
@streamable
class HarvesterHandshake(Streamable):
    farmer_public_keys: List[G1Element]
    pool_public_keys: List[G1Element]


@dataclass(frozen=True)
@streamable
class NewSignagePointHarvester(Streamable):
    challenge_hash: bytes32
    difficulty: uint64
    sub_slot_iters: uint64
    signage_point_index: uint8
    sp_hash: bytes32
    pool_difficulties: List[PoolDifficulty]
    stakings: List[Tuple[G1Element, str]]  # difficulty_coeff of each farmer public key's puzzle hash


@dataclass(frozen=True)
@streamable
class NewProofOfSpace(Streamable):
    challenge_hash: bytes32
    sp_hash: bytes32
    plot_identifier: str
    proof: ProofOfSpace
    signage_point_index: uint8
    difficulty_coeff: str


@dataclass(frozen=True)
@streamable
class RequestSignatures(Streamable):
    plot_identifier: str
    challenge_hash: bytes32
    sp_hash: bytes32
    messages: List[bytes32]


@dataclass(frozen=True)
@streamable
class RespondSignatures(Streamable):
    plot_identifier: str
    challenge_hash: bytes32
    sp_hash: bytes32
    local_pk: G1Element
    farmer_pk: G1Element
    message_signatures: List[Tuple[bytes32, G2Element]]


@dataclass(frozen=True)
@streamable
class Plot(Streamable):
    filename: str
    size: uint8
    plot_id: bytes32
    pool_public_key: Optional[G1Element]
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element
    file_size: uint64
    time_modified: uint64
    farmer_public_key: G1Element


@dataclass(frozen=True)
@streamable
class RequestPlots(Streamable):
    pass


@dataclass(frozen=True)
@streamable
class RespondPlots(Streamable):
    plots: List[Plot]
    failed_to_open_filenames: List[str]
    no_key_filenames: List[str]
