from dataclasses import dataclass
from typing import List

from src.types.full_block import FullBlock
from src.types.spend_bundle import SpendBundle
from src.types.header_block import HeaderBlock
from src.types.unfinished_block import UnfinishedBlock
from src.types.vdf import ProofOfTime
from src.types.sized_bytes import bytes32
from src.util.cbor_message import cbor_message
from src.util.ints import uint8, uint32, uint64, uint128
from src.types.peer_info import TimestampedPeerInfo

"""
Protocol between full nodes.
"""


@dataclass(frozen=True)
@cbor_message
class NewTip:
    height: uint32
    weight: uint128
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RemovingTip:
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class NewTransaction:
    transaction_id: bytes32
    cost: uint64
    fees: uint64


@dataclass(frozen=True)
@cbor_message
class RequestTransaction:
    transaction_id: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondTransaction:
    transaction: SpendBundle


@dataclass(frozen=True)
@cbor_message
class RejectTransactionRequest:
    transaction_id: bytes32


@dataclass(frozen=True)
@cbor_message
class NewProofOfTime:
    height: uint32
    challenge_hash: bytes32
    number_of_iterations: uint64
    witness_type: uint8


@dataclass(frozen=True)
@cbor_message
class RequestProofOfTime:
    height: uint32
    challenge_hash: bytes32
    number_of_iterations: uint64
    witness_type: uint8


@dataclass(frozen=True)
@cbor_message
class RespondProofOfTime:
    proof: ProofOfTime


@dataclass(frozen=True)
@cbor_message
class RejectProofOfTimeRequest:
    challenge_hash: bytes32
    number_of_iterations: uint64


@dataclass(frozen=True)
@cbor_message
class NewUnfinishedBlock:
    previous_header_hash: bytes32
    number_of_iterations: uint64
    new_header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RequestUnfinishedBlock:
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondUnfinishedBlock:
    block: UnfinishedBlock


@dataclass(frozen=True)
@cbor_message
class RejectUnfinishedBlockRequest:
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RequestBlock:
    height: uint32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondBlock:
    block: FullBlock


@dataclass(frozen=True)
@cbor_message
class RejectBlockRequest:
    height: uint32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RequestAllHeaderHashes:
    tip_header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class AllHeaderHashes:
    header_hashes: List[bytes32]


@dataclass(frozen=True)
@cbor_message
class RequestHeaderBlock:
    height: uint32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondHeaderBlock:
    header_block: HeaderBlock


@dataclass(frozen=True)
@cbor_message
class RejectHeaderBlockRequest:
    height: uint32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RequestMempoolTransactions:
    filter: bytes


@dataclass(frozen=True)
@cbor_message
class RequestPeers:
    """
    Return full list of peers
    """


@dataclass(frozen=True)
@cbor_message
class RespondPeers:
    peer_list: List[TimestampedPeerInfo]
