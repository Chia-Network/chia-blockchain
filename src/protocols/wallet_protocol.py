from dataclasses import dataclass
from typing import List, Tuple

from src.types.body import Body
from src.types.hashable.SpendBundle import SpendBundle
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.cbor_message import cbor_message
from src.util.ints import uint32


"""
Protocol between wallet (SPV node) and full node.
"""


@dataclass(frozen=True)
@cbor_message
class SendTransaction:
    transaction: SpendBundle


@dataclass(frozen=True)
@cbor_message
class NewLCA:
    lca_hash: bytes32
    height: uint32


@dataclass(frozen=True)
@cbor_message
class RequestHeader:
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class Header:
    header_block: HeaderBlock
    bip158_filter: bytes


@dataclass(frozen=True)
@cbor_message
class RequestAncestors:
    header_hash: bytes32
    previous_heights_desired: List[uint32]


@dataclass(frozen=True)
@cbor_message
class Ancestors:
    header_hash: bytes32
    List[Tuple[uint32, bytes32]]


@dataclass(frozen=True)
@cbor_message
class RequestBody:
    body_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondBody:
    body: Body
