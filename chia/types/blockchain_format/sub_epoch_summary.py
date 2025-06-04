from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia.consensus.mmr import MerkleMountainRange
from chia.util.hash import std_hash
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class SubEpochSummary(Streamable):
    """
    A summary of a sub-epoch. This gets stored in the consensus process when a sub-epoch / epoch ends.
    It is used to generate future challenge chains and reward chains.
    """

    prev_subepoch_summary_hash: bytes32  # Hash of the previous sub-epoch summary
    reward_chain_hash: bytes32  # Hash of the reward chain at end of sub-epoch
    num_blocks_overflow: uint8  # Number of overflow blocks in this sub-epoch
    new_difficulty: Optional[uint64]  # New difficulty if there is a change
    new_sub_slot_iters: Optional[uint64]  # New sub slot iters if there is a change

    # New fields for MMR support
    header_hash_mmr: MerkleMountainRange  # MMR of all header hashes in this sub-epoch
    vdf_mmr: MerkleMountainRange  # MMR of all VDF info and classgroup elements in this sub-epoch

    def get_hash(self) -> bytes32:
        """Return hash of the sub epoch summary"""
        # Hash all fields together
        fields = [
            self.prev_subepoch_summary_hash,
            self.reward_chain_hash,
            bytes([self.num_blocks_overflow]),
            bytes(8) if self.new_difficulty is None else bytes(self.new_difficulty),
            bytes(8) if self.new_sub_slot_iters is None else bytes(self.new_sub_slot_iters),
            self.header_hash_mmr.get_root(),
            self.vdf_mmr.get_root(),
        ]
        return std_hash(b"".join(fields))
