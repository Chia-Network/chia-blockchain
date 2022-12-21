from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class SubEpochSummary(Streamable):
    prev_subepoch_summary_hash: bytes32
    reward_chain_hash: bytes32  # hash of reward chain at end of last segment
    num_blocks_overflow: uint8  # How many more blocks than 384*(N-1)
    new_difficulty: Optional[uint64]  # Only once per epoch (diff adjustment)
    new_sub_slot_iters: Optional[uint64]  # Only once per epoch (diff adjustment)
