import logging
from typing import Dict, List, Optional, Tuple

from src.consensus.constants import ConsensusConstants
from src.types.challenge_slot import ChallengeSlot
from src.types.full_block import FullBlock
from src.types.reward_chain_end_of_slot import RewardChainEndOfSlot, EndOfSlotProofs
from src.types.sized_bytes import bytes32
from src.types.unfinished_block import UnfinishedBlock
from src.types.vdf import VDFProof, VDFInfo
from src.util.ints import uint32, uint8

log = logging.getLogger(__name__)

ICPs = List[Optional[Tuple[VDFInfo, VDFProof]]]


class FullNodeStore:
    # TODO(mariano): replace
    # Proof of time heights
    # proof_of_time_heights: Dict[Tuple[bytes32, uint64], uint32]
    constants: ConsensusConstants
    # Blocks which we have created, but don't have plot signatures yet
    candidate_blocks: Dict[bytes32, UnfinishedBlock]
    # Header hashes of unfinished blocks that we have seen recently
    seen_unfinished_blocks: set
    # Blocks which we have received but our blockchain does not reach, old ones are cleared
    disconnected_blocks: Dict[bytes32, FullBlock]
    # Unfinished blocks, keyed from reward hash
    unfinished_blocks: Dict[bytes32, UnfinishedBlock]

    # Finished slots and icps from the peak's slot onwards
    # We store all 32 ICPs for each slot, starting as 32 Nones and filling them as we go
    finished_slots: List[
        Tuple[ChallengeSlot, RewardChainEndOfSlot, EndOfSlotProofs, ICPs]
    ]

    @classmethod
    async def create(cls, constants: ConsensusConstants):
        self = cls()
        # TODO(mariano): replace
        # self.proof_of_time_heights = {}

        self.constants = constants
        self.clear_slots()
        self.unfinished_blocks = {}
        self.candidate_blocks = {}
        self.seen_unfinished_blocks = set()
        self.disconnected_blocks = {}
        return self

    def add_disconnected_block(self, block: FullBlock) -> None:
        self.disconnected_blocks[block.header_hash] = block

    def get_disconnected_block_by_prev(
        self, prev_header_hash: bytes32
    ) -> Optional[FullBlock]:
        for _, block in self.disconnected_blocks.items():
            if block.prev_header_hash == prev_header_hash:
                return block
        return None

    def get_disconnected_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.disconnected_blocks.get(header_hash, None)

    def clear_disconnected_blocks_below(self, height: uint32) -> None:
        for key in list(self.disconnected_blocks.keys()):
            if self.disconnected_blocks[key].height < height:
                del self.disconnected_blocks[key]

    def add_candidate_block(
        self,
        quality_string: bytes32,
        unfinished_block: UnfinishedBlock,
    ):
        self.candidate_blocks[quality_string] = unfinished_block

    def get_candidate_block(self, quality_string: bytes32) -> Optional[UnfinishedBlock]:
        return self.candidate_blocks.get(quality_string, None)

    def clear_candidate_blocks_below(self, height: uint32) -> None:
        del_keys = []
        for key, value in self.candidate_blocks.items():
            if value[4] < height:
                del_keys.append(key)
        for key in del_keys:
            try:
                del self.candidate_blocks[key]
            except KeyError:
                pass

    def add_unfinished_block(self, unfinished_block: UnfinishedBlock) -> None:
        self.unfinished_blocks[
            unfinished_block.reward_chain_sub_block.get_hash()
        ] = unfinished_block

    def get_unfinished_block(
        self, unfinished_reward_hash: bytes32
    ) -> Optional[UnfinishedBlock]:
        return self.unfinished_blocks.get(unfinished_reward_hash, None)

    def seen_unfinished_block(self, temp_header_hash: bytes32) -> bool:
        if temp_header_hash in self.seen_unfinished_blocks:
            return True
        self.seen_unfinished_blocks.add(temp_header_hash)
        return False

    def clear_seen_unfinished_blocks(self) -> None:
        self.seen_unfinished_blocks.clear()

    def get_unfinished_blocks(self) -> Dict[bytes32, UnfinishedBlock]:
        return self.unfinished_blocks

    def clear_unfinished_blocks_below(self, height: uint32) -> None:
        for partial_reward_hash, unfinished_block in self.unfinished_blocks.items():
            if unfinished_block.height < height:
                del self.unfinished_blocks[partial_reward_hash]

    def remove_unfinished_block(self, partial_reward_hash: bytes32):
        if partial_reward_hash in self.unfinished_blocks:
            del self.unfinished_blocks[partial_reward_hash]

    def clear_slots(self):
        self.finished_slots.clear()

    def new_finished_slot(
        self, cs: ChallengeSlot, reward: RewardChainEndOfSlot, proofs: EndOfSlotProofs
    ):
        """
        Returns true if finished slot successfully added
        """
        icps = [None] * self.constants.NUM_CHECKPOINTS_PER_SLOT
        if len(self.finished_slots) == 0:
            self.finished_slots.append((cs, reward, proofs, icps))
            return True
        if cs.proof_of_space.challenge_hash != self.finished_slots[-1][0].get_hash():
            # This slot does not append to our next slot
            return False
        self.finished_slots.append((cs, reward, proofs, icps))
        return True

    def new_icp(
        self, challenge_hash: bytes32, index: uint8, vdf_info: VDFInfo, proof: VDFProof
    ) -> bool:
        """
        Returns true if icp successfully added
        """
        for cs, reward, proofs, icps in self.finished_slots:
            if cs.get_hash() == challenge_hash:
                icps[index] = (vdf_info, proof)
                return True
        return False

    # TODO(mariano)
    # def add_proof_of_time_heights(self, challenge_iters: Tuple[bytes32, uint64], height: uint32) -> None:
    #     self.proof_of_time_heights[challenge_iters] = height
    #
    # def get_proof_of_time_heights(self, challenge_iters: Tuple[bytes32, uint64]) -> Optional[uint32]:
    #     return self.proof_of_time_heights.get(challenge_iters, None)
    #
    # def clear_proof_of_time_heights_below(self, height: uint32) -> None:
    #     del_keys: List = []
    #     for key, value in self.proof_of_time_heights.items():
    #         if value < height:
    #             del_keys.append(key)
    #     for key in del_keys:
    #         try:
    #             del self.proof_of_time_heights[key]
    #         except KeyError:
    #             pass
