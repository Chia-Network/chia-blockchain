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

"""
If already seen, ignore
Validate transaction
If consistent with at least 1/3 heads, store in mempool
Propagate transaction
"""
@cbor_message(tag=4000)
class NewTransaction:
    transaction: Transaction


"""
TODO(alex): update this
If already seen, ignore
If prev block not a head, ignore
Call self.ProofOfTimeFinished
Propagate PoT (?)
"""
@cbor_message(tag=4001)
class NewProofOfTime:
    proof: ProofOfTime


"""
TODO(alex): update this
If not a child of a head, ignore
If we have a PoT to complete this block, call self.Block
Otherwise: validate, store, and propagate
"""
@cbor_message(tag=4002)
class UnfinishedBlock:
    # Block that does not have ProofOfTime and Challenge
    block: FullBlock


"""
If have block, return block
TODO: request blocks?
"""
@cbor_message(tag=4003)
class RequestBlock:
    header_hash: bytes32


"""
TODO(alex): update this
If already have, ignore
If not child of a head, or ancestor of a head, ignore
Add block to head
    - Validate block
If heads updated, propagate block to full nodes, farmers, timelords
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
