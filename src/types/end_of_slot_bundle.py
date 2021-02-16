from dataclasses import dataclass
from typing import Optional

from src.types.blockchain_format.slots import ChallengeChainSubSlot, InfusedChallengeChainSubSlot
from src.types.blockchain_format.slots import RewardChainSubSlot, SubSlotProofs
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class EndOfSubSlotBundle(Streamable):
    challenge_chain: ChallengeChainSubSlot
    infused_challenge_chain: Optional[InfusedChallengeChainSubSlot]
    reward_chain: RewardChainSubSlot
    proofs: SubSlotProofs
