from dataclasses import dataclass
from typing import Optional, List

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
    reward_infusion_output: bytes32  # The reward chain infusion output, input to next VDF
    ips: uint64  # Current network iterations per second parameter
    pool_puzzle_hash: bytes32  # Need to keep track of these because Coins are created in a future block
    farmer_puzzle_hash: bytes32

    # Challenge block (present iff makes_challenge_block)
    challenge_chain_data_hash: Optional[bytes32]  # The hash of ChallengeChain data
    required_iters: Optional[uint64]  # The number of iters required for this proof of space

    # Block (present iff is_block)
    timestamp: Optional[uint64]
    prev_block_hash: Optional[bytes32]  # Header hash of the previous transaction block

    # Slot (present iff this is the first SB in slot)
    finished_challenge_slot_hashes: Optional[List[bytes32]]
    finished_reward_slot_hashes: Optional[List[bytes32]]
    deficit: Optional[uint8]  # Deficit at the START of the slot, before this block is included
    previous_slot_non_overflow_infusions: Optional[bool]

    # Sub-epoch (present iff this is the first SB after sub-epoch)
    sub_epoch_summary_included_hash: Optional[bytes32]

    @property
    def height(self):
        return self.sub_block_height

    @property
    def is_block(self):
        return self.timestamp is not None

    @property
    def makes_challenge_block(self):
        return self.challenge_chain_data_hash is not None

    @property
    def first_in_slot(self):
        return self.finished_challenge_slot_hashes is not None
