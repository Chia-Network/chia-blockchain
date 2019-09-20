from src.util.ints import uint64
from typing import List
from src.util.cbor_message import cbor_message
from src.types.sized_bytes import bytes32
from src.types.transaction import Transaction
from src.types.proof_of_time import ProofOfTime
from src.types.trunk_block import TrunkBlock
from src.types.full_block import FullBlock
from src.types.peer_info import PeerInfo

"""
Protocol between full nodes.
"""


"""
Receive a transaction from a peer.
"""
@cbor_message(tag=4000)
class NewTransaction:
    transaction: Transaction


"""
Receive a new proof of time from a peer.
"""
@cbor_message(tag=4001)
class NewProofOfTime:
    proof: ProofOfTime


"""
Receive an unfinished block from a peer.
"""
@cbor_message(tag=4002)
class UnfinishedBlock:
    # Block that does not have ProofOfTime and Challenge
    block: FullBlock


"""
Requests a block from a peer.
"""
@cbor_message(tag=4003)
class RequestBlock:
    header_hash: bytes32


"""
Receive a block from a peer.
"""
@cbor_message(tag=4004)
class Block:
    block: FullBlock


"""
Return full list of peers
"""
@cbor_message(tag=4005)
class RequestPeers:
    pass


"""
Update list of peers
"""
@cbor_message(tag=4006)
class Peers:
    peer_list: List[PeerInfo]


"""
Request trunks of blocks that are ancestors of the specified tip.
"""
@cbor_message(tag=4007)
class RequestTrunkBlocks:
    tip_header_hash: bytes32
    heights: List[uint64]


"""
Sends trunk blocks that are ancestors of the specified tip, at the specified heights.
"""
@cbor_message(tag=4008)
class TrunkBlocks:
    tip_header_hash: bytes32
    trunk_blocks: List[TrunkBlock]


"""
Request download of blocks, in the blockchain that has 'tip_header_hash' as the tip
"""
@cbor_message(tag=4009)
class RequestSyncBlocks:
    tip_header_hash: bytes32
    heights: List[uint64]


"""
Send blocks to peer.
"""
@cbor_message(tag=4010)
class SyncBlocks:
    tip_header_hash: bytes32
    blocks: List[FullBlock]
