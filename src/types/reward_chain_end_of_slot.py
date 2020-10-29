from dataclasses import dataclass
from src.types.sized_bytes import bytes32
from src.util.ints import uint8
from src.util.streamable import Streamable, streamable
from src.types.vdf import VDFInfo, VDFProof


@dataclass(frozen=True)
@streamable
class RewardChainEndOfSlot(Streamable):
    end_of_slot_vdf: VDFInfo
    challenge_slot_hash: bytes32
    deficit: uint8  # 5 or less. usually zero


@dataclass(frozen=True)
@streamable
class EndOfSlotProofs(Streamable):
    challenge_chain_slot_proof: VDFProof
    reward_chain_slot_proof: VDFProof
