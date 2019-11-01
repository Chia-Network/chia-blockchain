from typing import List
from src.util.cbor_message import cbor_message
from src.util.ints import uint32
from src.types.sized_bytes import bytes32
from src.types.block_body import BlockBody
from src.types.challenge import Challenge
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime
from src.types.transaction import Transaction
from dataclasses import dataclass

"""
Protocol between wallet (SPV node) and full node.
"""


@dataclass(frozen=True)
@cbor_message
class SendTransaction:
    transaction: Transaction


@dataclass(frozen=True)
@cbor_message
class NewHead:
    header_hash: bytes32
    height: uint32


@dataclass(frozen=True)
@cbor_message
class RequestHeaders:
    header_hash: bytes32
    previous_heights_desired: List[uint32]


@dataclass(frozen=True)
@cbor_message
class Headers:
    proof_of_time: ProofOfTime
    proof_of_space: ProofOfSpace
    challenge: Challenge
    bip158_filter: bytes


@dataclass(frozen=True)
@cbor_message
class RequestBody:
    body_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondBody:
    body: BlockBody
