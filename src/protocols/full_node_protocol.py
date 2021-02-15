from dataclasses import dataclass
from typing import List, Optional

from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.blockchain_format.slots import SubSlotProofs
from src.types.spend_bundle import SpendBundle
from src.types.unfinished_block import UnfinishedBlock
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.blockchain_format.vdf import VDFInfo, VDFProof
from src.types.weight_proof import WeightProof
from src.util.ints import uint8, uint32, uint64, uint128
from src.types.peer_info import TimestampedPeerInfo
from src.util.streamable import Streamable, streamable

"""
Protocol between full nodes.
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


@dataclass(frozen=True)
@streamable
class NewPeak(Streamable):
    header_hash: bytes32
    height: uint32
    weight: uint128
    fork_point_with_previous_peak: uint32
    unfinished_reward_block_hash: bytes32


@dataclass(frozen=True)
@streamable
class NewTransaction(Streamable):
    transaction_id: bytes32
    cost: uint64
    fees: uint64


@dataclass(frozen=True)
@streamable
class RequestTransaction(Streamable):
    transaction_id: bytes32


@dataclass(frozen=True)
@streamable
class RespondTransaction(Streamable):
    transaction: SpendBundle


@dataclass(frozen=True)
@streamable
class RequestProofOfWeight(Streamable):
    total_number_of_blocks: uint32
    tip: bytes32


@dataclass(frozen=True)
@streamable
class RespondProofOfWeight(Streamable):
    wp: WeightProof
    tip: bytes32


@dataclass(frozen=True)
@streamable
class RequestBlock(Streamable):
    height: uint32
    include_transaction_block: bool


@dataclass(frozen=True)
@streamable
class RejectBlock(Streamable):
    height: uint32


@dataclass(frozen=True)
class RequestBlocks(Streamable):
    start_height: uint32
    end_height: uint32
    include_transaction_block: bool


@dataclass(frozen=True)
@streamable
class RespondBlocks(Streamable):
    start_height: uint32
    end_height: uint32
    blocks: List[FullBlock]


@dataclass(frozen=True)
@streamable
class RejectBlocks(Streamable):
    start_height: uint32
    end_height: uint32


@dataclass(frozen=True)
@streamable
class RespondBlock(Streamable):
    block: FullBlock


@dataclass(frozen=True)
@streamable
class NewUnfinishedBlock(Streamable):
    unfinished_reward_hash: bytes32


@dataclass(frozen=True)
@streamable
class RequestUnfinishedBlock(Streamable):
    unfinished_reward_hash: bytes32


@dataclass(frozen=True)
@streamable
class RespondUnfinishedBlock(Streamable):
    unfinished_block: UnfinishedBlock


@dataclass(frozen=True)
@streamable
class NewSignagePointOrEndOfSubSlot(Streamable):
    prev_challenge_hash: Optional[bytes32]
    challenge_hash: bytes32
    index_from_challenge: uint8
    last_rc_infusion: bytes32


@dataclass(frozen=True)
@streamable
class RequestSignagePointOrEndOfSubSlot(Streamable):
    challenge_hash: bytes32
    index_from_challenge: uint8
    last_rc_infusion: bytes32


@dataclass(frozen=True)
@streamable
class RespondSignagePoint(Streamable):
    index_from_challenge: uint8
    challenge_chain_vdf: VDFInfo
    challenge_chain_proof: VDFProof
    reward_chain_vdf: VDFInfo
    reward_chain_proof: VDFProof


@dataclass(frozen=True)
@streamable
class RespondEndOfSubSlot(Streamable):
    end_of_slot_bundle: EndOfSubSlotBundle


@dataclass(frozen=True)
@streamable
class RequestMempoolTransactions(Streamable):
    filter: bytes


@dataclass(frozen=True)
@streamable
class RequestCompactVDFs(Streamable):
    height: uint32


@dataclass(frozen=True)
@streamable
class RespondCompactVDFs(Streamable):
    height: uint32
    header_hash: bytes32
    end_of_slot_proofs: List[SubSlotProofs]  # List of challenge eos vdf and reward eos vdf
    cc_sp_proof: Optional[VDFProof]  # If not first sp
    rc_sp_proof: Optional[VDFProof]  # If not first sp
    cc_ip_proof: VDFProof
    icc_ip_proof: Optional[VDFProof]
    rc_ip_proof: VDFProof


@dataclass(frozen=True)
@streamable
class RequestPeers(Streamable):
    """
    Return full list of peers
    """


@dataclass(frozen=True)
@streamable
class RespondPeers(Streamable):
    peer_list: List[TimestampedPeerInfo]
