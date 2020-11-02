from dataclasses import dataclass

from src.types.challenge_slot import ChallengeChainSubSlot, InfusedChallengeChainSubSlot
from src.types.reward_chain_end_of_slot import RewardChainSubSlot, SubSlotProofs
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
