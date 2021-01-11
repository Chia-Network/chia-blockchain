from dataclasses import dataclass
from typing import List, Tuple, Optional

from src.types.coin import Coin
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.cbor_message import cbor_message
from src.util.ints import uint32, uint128
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.util.streamable import Streamable, streamable

"""
Protocol between wallet (SPV node) and full node.
"""


@dataclass(frozen=True)
@cbor_message
class RequestPuzzleSolution:
    coin_name: bytes32
    sub_height: uint32


@dataclass(frozen=True)
@streamable
class PuzzleSolutionResponse(Streamable):
    coin_name: bytes32
    sub_height: uint32
    puzzle: Program
    solution: Program


@dataclass(frozen=True)
@cbor_message
class RespondPuzzleSolution:
    response: PuzzleSolutionResponse


@dataclass(frozen=True)
@streamable
class RejectPuzzleSolution:
    coin_name: bytes32
    sub_height: uint32


@dataclass(frozen=True)
@cbor_message
class SendTransaction:
    transaction: SpendBundle


@dataclass(frozen=True)
@cbor_message
class TransactionAck:
    txid: bytes32
    status: MempoolInclusionStatus
    error: Optional[str]


@dataclass(frozen=True)
@cbor_message
class NewPeak:
    header_hash: bytes32
    sub_block_height: uint32
    weight: uint128
    fork_point_with_previous_peak: uint32


@dataclass(frozen=True)
@cbor_message
class RequestSubBlockHeader:
    sub_height: uint32


@dataclass(frozen=True)
@cbor_message
class RespondSubBlockHeader:
    header_block: HeaderBlock


@dataclass(frozen=True)
@cbor_message
class RejectHeaderRequest:
    height: uint32


@dataclass(frozen=True)
@cbor_message
class RequestRemovals:
    sub_height: uint32
    header_hash: bytes32
    coin_names: Optional[List[bytes32]]


@dataclass(frozen=True)
@cbor_message
class RespondRemovals:
    sub_height: uint32
    header_hash: bytes32
    coins: List[Tuple[bytes32, Optional[Coin]]]
    proofs: Optional[List[Tuple[bytes32, bytes]]]


@dataclass(frozen=True)
@cbor_message
class RejectRemovalsRequest:
    sub_height: uint32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RequestAdditions:
    sub_height: uint32
    header_hash: bytes32
    puzzle_hashes: Optional[List[bytes32]]


@dataclass(frozen=True)
@cbor_message
class RespondAdditions:
    sub_height: uint32
    header_hash: bytes32
    coins: List[Tuple[bytes32, List[Coin]]]
    proofs: Optional[List[Tuple[bytes32, bytes, Optional[bytes]]]]


@dataclass(frozen=True)
@cbor_message
class RejectAdditionsRequest:
    sub_height: uint32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RequestHeaderBlocks:
    start_sub_height: uint32
    end_sub_height: uint32


@dataclass(frozen=True)
@cbor_message
class RejectHeaderBlocks:
    start_sub_height: uint32
    end_sub_height: uint32


@dataclass(frozen=True)
@cbor_message
class RespondHeaderBlocks:
    start_sub_height: uint32
    end_sub_height: uint32
    header_blocks: List[HeaderBlock]
