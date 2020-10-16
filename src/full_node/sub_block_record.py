from dataclasses import dataclass
from typing import Optional

from src.util.ints import uint32, uint64, uint128
from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable


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
    prev_block_hash: Optional[bytes32]  # Header hash of the previous transaction block
    sub_block_height: uint32
    weight: uint128  # Total cumulative difficulty of all ancestor blocks since genesis
    total_iters: uint128  # Total number of VDF iterations since genesis, including this sub-block
    is_block: bool  # Whether or not this sub-block is also a block
    challenge_chain_pos_hash: bytes32  # The hash of the proof of space in challenge chain
    required_iters: uint64  # The number of iters required for this proof of space
    first_block_in_challenge_slot: bool
    ips: uint64  # Current network iterations per second parameter
    pool_puzzle_hash: bytes32  # Need to keep track of these because Coins are created in a future block
    farmer_puzzle_hash: bytes32
    timestamp: Optional[uint64]  # Present iff is_block
    finished_challenge_slot_hash: Optional[bytes32]  # Present iff this is the first SB after slot
    finished_reward_slot_hash: Optional[bytes32]  # Present iff this is the first SB after slot

    @property
    def height(self):
        return self.sub_block_height
