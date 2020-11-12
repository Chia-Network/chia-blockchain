from dataclasses import dataclass
from typing import List, Optional

from blspy import G2Element

from src.types.header_block import HeaderBlock
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint8, uint64, uint32
from src.util.streamable import Streamable, streamable
from src.types.vdf import VDFProof


@dataclass(frozen=True)
@streamable
class SubEpochData(Streamable):
    reward_chain_hash: bytes32  # hash of reward chain at end of last segment
    # Number of subblocks overflow in previous subepoch
    previous_sub_epoch_overflows: uint8
    # (at end of epoch) New work difficulty and iterations per subslot
    sub_slot_iters: Optional[uint64]
    new_difficulty: Optional[uint64]


@dataclass(frozen=True)
@streamable
class SubepochChallengeSegment(Streamable):
    sub_epoch_n: uint32
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
    sub_epoch_data: List[SubEpochData]
    sub_epoch_segments: List[SubepochChallengeSegment]
    header_block: List[HeaderBlock]
