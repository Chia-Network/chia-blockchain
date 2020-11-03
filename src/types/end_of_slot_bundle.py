from dataclasses import dataclass

from src.types.slots import ChallengeChainSubSlot, InfusedChallengeChainSubSlot
from src.types.slots import RewardChainSubSlot, SubSlotProofs
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class EndOfSubSlotBundle(Streamable):
    challenge_chain: ChallengeChainSubSlot
    infused_challenge_chain: InfusedChallengeChainSubSlot
    reward_chain: RewardChainSubSlot
    proofs: SubSlotProofs

    def get_challenge_hash(self):
        return self.challenge_chain.get_hash()

    def get_prev_challenge_hash(self):
        return self.challenge_chain.challenge_chain_end_of_slot_vdf.challenge_hash
