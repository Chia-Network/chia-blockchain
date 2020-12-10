from typing import Optional
from dataclasses import dataclass

from src.types.sized_bytes import bytes32
from src.util.ints import uint8, uint64
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class SubEpochSummary(Streamable):
    prev_subepoch_summary_hash: bytes32
    reward_chain_hash: bytes32  # hash of reward chain at end of last segment
    num_sub_blocks_overflow: uint8  # How many more sub-blocks than 384*(N-1)
    new_difficulty: Optional[uint64]  # Only once per epoch (diff adjustment)
    new_sub_slot_iters: Optional[uint64]  # Only once per epoch (diff adjustment)
