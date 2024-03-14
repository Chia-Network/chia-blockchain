from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64

# This is a modified version of the TestBlockRecord from test_mempool_manager.py


@dataclass(frozen=True)
class TestBlockRecord:
    """
    This is a subset of BlockRecord that the cli tests need
    """

    header_hash: bytes32
    height: uint32
    timestamp: Optional[uint64]
    prev_transaction_block_height: uint32
    prev_transaction_block_hash: Optional[bytes32]
    prev_hash: Optional[bytes32]
    weight: uint64 = uint64(10000)
    fees: uint64 = uint64(5000)
    farmer_puzzle_hash: bytes32 = bytes32([1] * 32)
    pool_puzzle_hash: bytes32 = bytes32([2] * 32)
    sub_slot_iters: uint64 = uint64(1024)
    total_iters: uint64 = uint64(12081)
    deficit: uint8 = uint8(0)

    @property
    def is_transaction_block(self) -> bool:
        return self.timestamp is not None


def height_hash(height: int) -> bytes32:
    return bytes32(height.to_bytes(32, byteorder="big"))


def hash_to_height(int_bytes: bytes32) -> int:
    return int.from_bytes(int_bytes, byteorder="big")


def create_test_block_record(
    *, height: uint32 = uint32(11), timestamp: uint64 = uint64(10040), header_hash: Optional[bytes32] = None
) -> TestBlockRecord:
    if header_hash is None:
        header_hash = height_hash(height)
    else:
        height = uint32(hash_to_height(header_hash))  # so the heights make sense
    return TestBlockRecord(
        header_hash=header_hash,
        height=height,
        timestamp=timestamp,
        prev_transaction_block_height=uint32(height - 1),
        prev_transaction_block_hash=height_hash(height - 1),
        prev_hash=height_hash(height - 1),
    )
