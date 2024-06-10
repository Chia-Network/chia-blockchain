from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Tuple

import chia_rs

from chia.full_node.fee_estimate import FeeEstimateGroup
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import Streamable, streamable

"""
Protocol between wallet (SPV node) and full node.
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


CoinState = chia_rs.CoinState
RespondToPhUpdates = chia_rs.RespondToPhUpdates


@streamable
@dataclass(frozen=True)
class RequestPuzzleSolution(Streamable):
    coin_name: bytes32
    height: uint32


@streamable
@dataclass(frozen=True)
class PuzzleSolutionResponse(Streamable):
    coin_name: bytes32
    height: uint32
    puzzle: SerializedProgram
    solution: SerializedProgram


@streamable
@dataclass(frozen=True)
class RespondPuzzleSolution(Streamable):
    response: PuzzleSolutionResponse


@streamable
@dataclass(frozen=True)
class RejectPuzzleSolution(Streamable):
    coin_name: bytes32
    height: uint32


@streamable
@dataclass(frozen=True)
class SendTransaction(Streamable):
    transaction: SpendBundle


@streamable
@dataclass(frozen=True)
class TransactionAck(Streamable):
    txid: bytes32
    status: uint8  # MempoolInclusionStatus
    error: Optional[str]


@streamable
@dataclass(frozen=True)
class NewPeakWallet(Streamable):
    header_hash: bytes32
    height: uint32
    weight: uint128
    fork_point_with_previous_peak: uint32


@streamable
@dataclass(frozen=True)
class RequestBlockHeader(Streamable):
    height: uint32


@streamable
@dataclass(frozen=True)
class RespondBlockHeader(Streamable):
    header_block: HeaderBlock


@streamable
@dataclass(frozen=True)
class RejectHeaderRequest(Streamable):
    height: uint32


@streamable
@dataclass(frozen=True)
class RequestRemovals(Streamable):
    height: uint32
    header_hash: bytes32
    coin_names: Optional[List[bytes32]]


@streamable
@dataclass(frozen=True)
class RespondRemovals(Streamable):
    height: uint32
    header_hash: bytes32
    coins: List[Tuple[bytes32, Optional[Coin]]]
    proofs: Optional[List[Tuple[bytes32, bytes]]]


@streamable
@dataclass(frozen=True)
class RejectRemovalsRequest(Streamable):
    height: uint32
    header_hash: bytes32


@streamable
@dataclass(frozen=True)
class RequestAdditions(Streamable):
    height: uint32
    header_hash: Optional[bytes32]
    puzzle_hashes: Optional[List[bytes32]]


@streamable
@dataclass(frozen=True)
class RespondAdditions(Streamable):
    height: uint32
    header_hash: bytes32
    coins: List[Tuple[bytes32, List[Coin]]]
    proofs: Optional[List[Tuple[bytes32, bytes, Optional[bytes]]]]


@streamable
@dataclass(frozen=True)
class RejectAdditionsRequest(Streamable):
    height: uint32
    header_hash: bytes32


@streamable
@dataclass(frozen=True)
class RespondBlockHeaders(Streamable):
    start_height: uint32
    end_height: uint32
    header_blocks: List[HeaderBlock]


@streamable
@dataclass(frozen=True)
class RejectBlockHeaders(Streamable):
    start_height: uint32
    end_height: uint32


@streamable
@dataclass(frozen=True)
class RequestBlockHeaders(Streamable):
    start_height: uint32
    end_height: uint32
    return_filter: bool


@streamable
@dataclass(frozen=True)
class RequestHeaderBlocks(Streamable):
    start_height: uint32
    end_height: uint32


@streamable
@dataclass(frozen=True)
class RejectHeaderBlocks(Streamable):
    start_height: uint32
    end_height: uint32


@streamable
@dataclass(frozen=True)
class RespondHeaderBlocks(Streamable):
    start_height: uint32
    end_height: uint32
    header_blocks: List[HeaderBlock]


# This class is implemented in Rust
# @streamable
# @dataclass(frozen=True)
# class CoinState(Streamable):
#    coin: Coin
#    spent_height: Optional[uint32]
#    created_height: Optional[uint32]


@streamable
@dataclass(frozen=True)
class RegisterForPhUpdates(Streamable):
    puzzle_hashes: List[bytes32]
    min_height: uint32


# This class is implemented in Rust
# @streamable
# @dataclass(frozen=True)
# class RespondToPhUpdates(Streamable):
#    puzzle_hashes: List[bytes32]
#    min_height: uint32
#    coin_states: List[CoinState]


@streamable
@dataclass(frozen=True)
class RegisterForCoinUpdates(Streamable):
    coin_ids: List[bytes32]
    min_height: uint32


@streamable
@dataclass(frozen=True)
class RespondToCoinUpdates(Streamable):
    coin_ids: List[bytes32]
    min_height: uint32
    coin_states: List[CoinState]


@streamable
@dataclass(frozen=True)
class CoinStateUpdate(Streamable):
    height: uint32
    fork_height: uint32
    peak_hash: bytes32
    items: List[CoinState]


@streamable
@dataclass(frozen=True)
class RequestChildren(Streamable):
    coin_name: bytes32


@streamable
@dataclass(frozen=True)
class RespondChildren(Streamable):
    coin_states: List[CoinState]


@streamable
@dataclass(frozen=True)
class RequestSESInfo(Streamable):
    start_height: uint32
    end_height: uint32


@streamable
@dataclass(frozen=True)
class RespondSESInfo(Streamable):
    reward_chain_hash: List[bytes32]
    heights: List[List[uint32]]


@streamable
@dataclass(frozen=True)
class RequestFeeEstimates(Streamable):
    """
    time_targets (List[uint64]): Epoch timestamps in seconds to estimate FeeRates for.
    """

    time_targets: List[uint64]


@streamable
@dataclass(frozen=True)
class RespondFeeEstimates(Streamable):
    estimates: FeeEstimateGroup


@streamable
@dataclass(frozen=True)
class RequestRemovePuzzleSubscriptions(Streamable):
    puzzle_hashes: Optional[List[bytes32]]


@streamable
@dataclass(frozen=True)
class RespondRemovePuzzleSubscriptions(Streamable):
    puzzle_hashes: List[bytes32]


@streamable
@dataclass(frozen=True)
class RequestRemoveCoinSubscriptions(Streamable):
    coin_ids: Optional[List[bytes32]]


@streamable
@dataclass(frozen=True)
class RespondRemoveCoinSubscriptions(Streamable):
    coin_ids: List[bytes32]


@streamable
@dataclass(frozen=True)
class CoinStateFilters(Streamable):
    include_spent: bool
    include_unspent: bool
    include_hinted: bool
    min_amount: uint64


@streamable
@dataclass(frozen=True)
class RequestPuzzleState(Streamable):
    puzzle_hashes: List[bytes32]
    previous_height: Optional[uint32]
    header_hash: bytes32
    filters: CoinStateFilters
    subscribe_when_finished: bool


@streamable
@dataclass(frozen=True)
class RespondPuzzleState(Streamable):
    puzzle_hashes: List[bytes32]
    height: uint32
    header_hash: bytes32
    is_finished: bool
    coin_states: List[CoinState]


@streamable
@dataclass(frozen=True)
class RejectPuzzleState(Streamable):
    reason: uint8  # RejectStateReason


@streamable
@dataclass(frozen=True)
class RequestCoinState(Streamable):
    coin_ids: List[bytes32]
    previous_height: Optional[uint32]
    header_hash: bytes32
    subscribe: bool


@streamable
@dataclass(frozen=True)
class RespondCoinState(Streamable):
    coin_ids: List[bytes32]
    coin_states: List[CoinState]


@streamable
@dataclass(frozen=True)
class RejectCoinState(Streamable):
    reason: uint8  # RejectStateReason


class RejectStateReason(IntEnum):
    REORG = 0
    EXCEEDED_SUBSCRIPTION_LIMIT = 1


@streamable
@dataclass(frozen=True)
class RemovedMempoolItem(Streamable):
    transaction_id: bytes32
    reason: uint8  # MempoolRemoveReason


@streamable
@dataclass(frozen=True)
class MempoolItemsAdded(Streamable):
    transaction_ids: List[bytes32]


@streamable
@dataclass(frozen=True)
class MempoolItemsRemoved(Streamable):
    removed_items: List[RemovedMempoolItem]


@streamable
@dataclass(frozen=True)
class RequestCostInfo(Streamable):
    pass


@streamable
@dataclass(frozen=True)
class RespondCostInfo(Streamable):
    max_transaction_cost: uint64
    max_block_cost: uint64
    max_mempool_cost: uint64
    mempool_cost: uint64
    mempool_fee: uint64
    bump_fee_per_cost: uint8
