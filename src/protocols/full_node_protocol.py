from dataclasses import dataclass
from typing import List, Optional

from src.types.challenge_slot import ChallengeSlot
from src.types.full_block import FullBlock
from src.types.reward_chain_end_of_slot import RewardChainEndOfSlot, EndOfSlotProofs
from src.types.spend_bundle import SpendBundle
from src.types.unfinished_block import UnfinishedBlock
from src.types.sized_bytes import bytes32
from src.types.vdf import VDFInfo, VDFProof
from src.util.cbor_message import cbor_message
from src.util.ints import uint8, uint32, uint64, uint128, int32
from src.types.peer_info import TimestampedPeerInfo

"""
Protocol between full nodes.
"""


@dataclass(frozen=True)
@cbor_message
class NewPeak:
    header_hash: bytes32
    sub_block_height: uint32
    weight: uint128
    fork_point_with_previous_peak: bytes32


@dataclass(frozen=True)
@cbor_message
class RequestProofOfWeight:
    pass


@dataclass(frozen=True)
@cbor_message
class RespondProofOfWeight:
    # TODO(mariano/almog)
    pass


@dataclass(frozen=True)
@cbor_message
class RequestSubBlock:
    height: uint32


@dataclass(frozen=True)
@cbor_message
class RespondSubBlock:
    sub_block: FullBlock


@dataclass(frozen=True)
@cbor_message
class RequestCompactVDFs:
    height: uint32


@dataclass(frozen=True)
@cbor_message
class RespondCompactVDFs:
    height: uint32
    header_hash: bytes32
    end_of_slot_proofs: List[EndOfSlotProofs]  # List of challenge eos vdf and reward eos vdf
    cc_icp_proof: Optional[VDFProof]  # If not first icp
    rc_icp_proof: Optional[VDFProof]  # If not first icp
    cc_ip_proof: VDFProof
    rc_ip_proof: VDFProof


@dataclass(frozen=True)
@cbor_message
class NewInfusionChallengePointOrEndOfSlot:
    challenge_hash: uint32
    index_from_challenge: uint8


@dataclass(frozen=True)
@cbor_message
class RequestInfusionChallengePointOrEndOfSlot:
    challenge_hash: uint32
    index_from_challenge: int32


@dataclass(frozen=True)
@cbor_message
class RespondInfusionChallengePoint:
    challenge_hash: bytes32
    index: uint8
    challenge_chain_vdf: VDFInfo
    challenge_chain_proof: VDFProof
    reward_chain_vdf: VDFInfo
    reward_chain_proof: VDFProof


@dataclass(frozen=True)
@cbor_message
class RespondEndOfSlot:
    challenge_slot: ChallengeSlot
    reward_slot: RewardChainEndOfSlot
    slot_proofs: EndOfSlotProofs


@dataclass(frozen=True)
@cbor_message
class NewUnfinishedSubBlock:
    unfinished_reward_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RequestUnfinishedSubBlock:
    unfinished_reward_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class RespondUnfinishedSubBlock:
    unfinished_sub_block: UnfinishedBlock


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
