from dataclasses import dataclass
from typing import Optional, List

from src.consensus.constants import ConsensusConstants
from src.types.header_block import HeaderBlock
from src.types.sub_epoch_summary import SubEpochSummary
from src.util.ints import uint8, uint32, uint64, uint128
from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable
from src.types.classgroup import ClassgroupElement


@dataclass(frozen=True)
@streamable
class SubBlockRecord(Streamable):
    """
    This class is not included or hashed into the blockchain, but it is kept in memory as a more
    efficient way to maintain data about the blockchain. This allows us to validate future blocks,
    difficulty adjustments, etc, without saving the whole header block in memory.
    """

    header_hash: bytes32
    prev_hash: bytes32  # Header hash of the previous sub-block
    sub_block_height: uint32
    weight: uint128  # Total cumulative difficulty of all ancestor blocks since genesis
    total_iters: uint128  # Total number of VDF iterations since genesis, including this sub-block
    challenge_vdf_output: ClassgroupElement  # This is the intermediary VDF output at ip_iters in challenge chain
    infused_challenge_vdf_output: Optional[
        ClassgroupElement
    ]  # This is the intermediary VDF output at ip_iters in infused cc, iff deficit <= 3
    reward_infusion_new_challenge: bytes32  # The reward chain infusion output, input to next VDF
    challenge_block_info_hash: bytes32  # Hash of challenge chain data, used to validate end of slots in the future
    ips: uint64  # Current network iterations per second parameter
    pool_puzzle_hash: bytes32  # Need to keep track of these because Coins are created in a future block
    farmer_puzzle_hash: bytes32
    required_iters: uint64  # The number of iters required for this proof of space
    deficit: uint8  # A deficit of 5 is an overflow block after an infusion. Deficit of 4 is a challenge block

    # Block (present iff is_block)
    timestamp: Optional[uint64]
    prev_block_hash: Optional[bytes32]  # Header hash of the previous transaction block

    # Slot (present iff this is the first SB in sub slot)
    finished_challenge_slot_hashes: Optional[List[bytes32]]
    finished_infused_challenge_slot_hashes: Optional[List[bytes32]]
    finished_reward_slot_hashes: Optional[List[bytes32]]

    # Sub-epoch (present iff this is the first SB after sub-epoch)
    sub_epoch_summary_included: Optional[SubEpochSummary]

    @property
    def height(self):
        return self.sub_block_height

    @property
    def is_block(self):
        return self.timestamp is not None

    @property
    def first_in_sub_slot(self):
        return self.finished_challenge_slot_hashes is not None

    def is_challenge_sub_block(self, constants: ConsensusConstants):
        return self.deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1

    def get_header(self) -> HeaderBlock:
        header_block = HeaderBlock(
            self.finished_sub_slots,
            self.reward_chain_sub_block,
            self.challenge_chain_sp_proof,
            self.challenge_chain_ip_proof,
            self.reward_chain_sp_proof,
            self.reward_chain_ip_proof,
            self.infused_challenge_chain_ip_proof,
            self.foliage_sub_block,
            self.foliage_block,
            b"",  # No filter
        )
        return header_block
