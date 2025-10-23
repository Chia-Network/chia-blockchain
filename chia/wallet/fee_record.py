from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable

_T_FeeRecord = TypeVar("_T_FeeRecord", bound="FeeRecord")


@streamable
@dataclass(frozen=True)
class FeePerCost(Streamable):
    fee: uint64
    cost: uint64

    def as_float(self) -> float:
        return float(self.fee) / float(self.cost)


@dataclass(frozen=True)
@streamable
class FeeRecordKey(Streamable):
    block_hash: bytes32
    estimator_name: str
    estimator_version: uint8


@streamable
@dataclass(frozen=True)
class FeeRecord(Streamable):
    """
    A FeeRecord captures historical information about the mempool
    At least one FeeRecord is generated for every new transaction block
    Storing this information in the wallet simplifies lite wallet
    operation, making it more independent, and decreasing network traffic


    #max_block_clvm_cost
    #mempool_max_size
    """

    block_index: uint32
    block_time: uint64  # seconds
    block_fpc: FeePerCost  # total mojos in fees divided by total clvm_cost in the block
    estimated_fpc: FeePerCost
    fee_to_add_std_tx: uint64  # mojos
    current_mempool_cost: uint64
    current_mempool_fees: uint64
    minimum_fee_per_cost_to_replace: FeePerCost
