from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from chia_rs import CoinState, RespondToPhUpdates

from chia.full_node.fee_estimate import FeeEstimateGroup
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import Streamable, streamable

"""
Protocol between wallet (SPV node) and full node.
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


__all__ = ["CoinState", "RespondToPhUpdates"]


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
