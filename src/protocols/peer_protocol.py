from typing import List
from src.util.cbor_message import cbor_message
from src.types.sized_bytes import bytes32
from src.types.transaction import Transaction
from src.types.proof_of_time import ProofOfTime
from src.types.full_block import FullBlock
from src.types.peer_info import PeerInfo

"""
Protocol between full nodes.
"""


@cbor_message(tag=4000)
class NewTransaction:
    transaction: Transaction


@cbor_message(tag=4001)
class NewProofOfTime:
    proof: ProofOfTime


@cbor_message(tag=4002)
class UnfinishedBlock:
    # Block that does not have ProofOfTime and Challenge
    block: FullBlock


@cbor_message(tag=4003)
class RequestBlock:
    header_hash: bytes32


@cbor_message(tag=4004)
class Block:
    block: FullBlock


@cbor_message(tag=4005)
class RequestPeers:
    pass


@cbor_message(tag=4006)
class Peers:
    peer_list: List[PeerInfo]
