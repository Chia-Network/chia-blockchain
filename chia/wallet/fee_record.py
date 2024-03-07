from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from chia.full_node.fee_estimation import FeeMempoolInfo
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable

_T_FeeRecord = TypeVar("_T_FeeRecord", bound="FeeRecord")


@streamable
@dataclass(frozen=True)
class FeeRecord(Streamable):
    """
    A FeeRecord captures historical information about the mempool
    At least one FeeRecord is generated for every new transaction block
    Storing this information in the wallet simplifies lite wallet
    operation, making it more independent, and decreasing network traffic
    """

    # block_hash: bytes32
    block_index: uint32
    block_fpc: float
    block_time: uint64
    estimated_fpc: float
    estimate_type: str
    estimate_version: uint8
    fpc_to_add_std_tx: uint64
    fee_mempool_info: FeeMempoolInfo
    # fpc_needed_to_add_std_tx: float
