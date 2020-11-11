from typing import List, Optional

from attr import dataclass
from blspy import G2Element

from src.types.header_block import HeaderBlock
from src.types.proof_of_space import ProofOfSpace
from src.types.vdf import VDFProof

from src.types.sized_bytes import bytes32

from src.util import streamable
from src.util.ints import uint64, uint32
from src.util.streamable import Streamable


@dataclass(frozen=True)
@streamable
class InfusedChallengeChains(Streamable):

    # VDF from beginning to end of subslot
    start_to_end_sublot_vdf: Optional[VDFProof]  # if not infused

    # Proof of space
    proof_of_space: Optional[ProofOfSpace]  # if infused

    # VDF to signage point
    signage_point_vdf: Optional[VDFProof]  # if infused

    # VDF to signage point
    signage_point_vdf: Optional[VDFProof]  # if infused

    # VDF from infusion point to end of subslot
    infusion_to_slot_end_vdf: Optional[VDFProof]  # if infused


@dataclass(frozen=True)
@streamable
class SubEpochData(Streamable):

    infused_challenge_chains = List[InfusedChallengeChains]
    # Hash of previous subepoch final reward chain slot end
    final_reward_chain_hash: bytes32
    # Number of subblocks overflow in previous subepoch
    prev_epoch_overflow_count: uint32
    # Hash of final challenge slot end
    final_challenge_chain_hash: bytes32
    # (at beginning of work difficulty reset) New work difficulty and iterations per subslot
    sub_slot_iters: Optional[uint64]
    new_difficulty: Optional[uint64]


@dataclass(frozen=True)
@streamable
class SubepochChallengeSegment(Streamable):

    # Proof of space
    proof_of_space: Optional[ProofOfSpace]  # if infused
    # VDF to signage point
    signage_point_vdf: Optional[VDFProof]  # if infused
    # Signature of signage point
    signage_point_sig: Optional[G2Element]  # if infused
    # VDF to infusion point
    infusion_point_vdf: Optional[VDFProof]  # if infused
    # VDF from infusion point to end of subslot
    infusion_to_slot_end_vdf: Optional[VDFProof]  # if infused

    # VDF from beginning to end of subslot
    slot_vdf: Optional[VDFProof]  # if not infused


@dataclass(frozen=True)
@streamable
class WeightProof(Streamable):

    peak: bytes32

    height: uint64

    sub_epoch_data: List[SubEpochData]

    sub_epoch_segments: List[SubepochChallengeSegment]
    # Recent reward chain
    header_block: List[HeaderBlock]
