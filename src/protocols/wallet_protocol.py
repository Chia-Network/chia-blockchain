from dataclasses import dataclass
from typing import List, Tuple, Optional

from src.types.hashable.coin import Coin
from src.types.hashable.spend_bundle import SpendBundle
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.cbor_message import cbor_message
from src.util.ints import uint32, uint64, uint128


"""
Protocol between wallet (SPV node) and full node.
"""


@dataclass(frozen=True)
@cbor_message
class SendTransaction:
    transaction: SpendBundle


@dataclass(frozen=True)
@cbor_message
class TransactionAck:
    txid: bytes32
    status: bool


@dataclass(frozen=True)
@cbor_message
class RequestAllProofHashes:
    pass


@dataclass(frozen=True)
@cbor_message
class RespondAllProofHashes:
    hashes: List[Tuple[bytes32, Optional[uint64]]]


@dataclass(frozen=True)
@cbor_message
class RequestAllHeaderHashesAfter:
    starting_height: uint32
    previous_challenge_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondAllHeaderHashesAfter:
    starting_height: uint32
    previous_challenge_hash: bytes32
    hashes: List[bytes32]


@dataclass(frozen=True)
@cbor_message
class RejectAllHeaderHashesAfterRequest:
    starting_height: uint32
    previous_challenge_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class NewLCA:
    lca_hash: bytes32
    height: uint32
    weight: uint128


@dataclass(frozen=True)
@cbor_message
class RequestHeader:
    height: uint32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondHeader:
    header_block: HeaderBlock
    bip158_filter: Optional[bytes]


@dataclass(frozen=True)
@cbor_message
class RejectHeaderRequest:
    height: uint32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RequestRemovals:
    height: uint32
    header_hash: bytes32
    coin_names: Optional[List[bytes32]]


@dataclass(frozen=True)
@cbor_message
class RespondRemovals:
    height: uint32
    header_hash: bytes32
    coins: List[Tuple[bytes32, Optional[Coin]]]
    proofs: Optional[List[Tuple[bytes32, bytes]]]


@dataclass(frozen=True)
@cbor_message
class RejectRemovalsRequest:
    height: uint32
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RequestAdditions:
    height: uint32
    header_hash: bytes32
    puzzle_hashes: Optional[List[bytes32]]


@dataclass(frozen=True)
@cbor_message
class RespondAdditions:
    height: uint32
    header_hash: bytes32
    coins: List[Tuple[bytes32, List[Coin]]]
    proofs: Optional[List[Tuple[bytes32, bytes, Optional[bytes]]]]


@dataclass(frozen=True)
@cbor_message
class RejectAdditionsRequest:
    height: uint32
    header_hash: bytes32
