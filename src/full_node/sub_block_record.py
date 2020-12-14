from dataclasses import dataclass
from typing import Optional, List

from src.util.ints import uint32, uint64, uint128
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
    prev_block_hash: Optional[bytes32]  # Header hash of the previous transaction block (iff is_block)
    sub_block_height: uint32
    weight: uint128  # Total cumulative difficulty of all ancestor blocks since genesis
    total_iters: uint128  # Total number of VDF iterations since genesis, including this sub-block
    is_block: bool  # Whether or not this sub-block is also a block
    challenge_chain_data_hash: Optional[bytes32]  # The hash of ChallengeChain data (iff makes_challenge_block)
    required_iters: Optional[uint64]  # The number of iters required for this proof of space (iff makes_challenge_block)
    challenge_vdf_output: ClassgroupElement  # This is the intermediary VDF output at ip_iters in challenge chain
    reward_infusion_output: bytes32  # The reward chain infusion output, input to next VDF
    makes_challenge_block: bool
    ips: uint64  # Current network iterations per second parameter
    pool_puzzle_hash: bytes32  # Need to keep track of these because Coins are created in a future block
    farmer_puzzle_hash: bytes32
    timestamp: Optional[uint64]  # (iff is_block)
    finished_challenge_slot_hashes: Optional[List[bytes32]]  # Present iff this is the first SB after slot
    finished_reward_slot_hashes: Optional[List[bytes32]]  # Present iff this is the first SB after slot
    sub_epoch_summary_included_hash: Optional[bytes32]  # If this is the first SB after sub-epoch

    @property
    def height(self):
        return self.sub_block_height
