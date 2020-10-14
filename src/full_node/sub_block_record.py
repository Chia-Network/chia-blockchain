from dataclasses import dataclass

from src.util.ints import uint32, uint64, uint128
from src.types.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class SubBlockRecord(Streamable):
    header_hash: bytes32
    prev_hash: bytes32
    sub_block_height: uint32
    weight: uint128
    total_iters: uint128
    slot_number: uint32  # Determines which PoSpace we are based off of
    challenge_slot_number: uint32  # Determines how many infusions happened in challenge chain
    overflows_slot: bool  # Determines whether infusion happens in next slot
    slot_iterations: uint64  # How many iterations are necessary for this slot to finish
    timestamp: uint64

    @property
    def height(self):
        return self.sub_block_height
