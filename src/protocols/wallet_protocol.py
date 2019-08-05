from typing import List
from src.util.cbor_message import cbor_message
from src.util.ints import uint32
from src.types.sized_bytes import bytes32
from src.types.block_body import BlockBody
from src.types.challenge import Challenge
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime, ProofOfTimeOutput
from src.types.transaction import Transaction

"""
Protocol between wallet (SPV node) and full node.
"""


@cbor_message(tag=6000)
class SendTransaction:
    transaction: Transaction


@cbor_message(tag=6001)
class NewHead:
    header_hash: bytes32
    height: uint32


@cbor_message(tag=6002)
class RequestHeaders:
    header_hash: bytes32
    previous_heights_desired: List[uint32]


@cbor_message(tag=6003)
class Headers:
    proof_of_time_output: ProofOfTimeOutput
    proof_of_time: ProofOfTime
    proof_of_space: ProofOfSpace
    challenge: Challenge
    bip158_filter: bytes


@cbor_message(tag=6004)
class RequestBody:
    body_hash: bytes32


@cbor_message(tag=6005)
class RespondBody:
    body: BlockBody
