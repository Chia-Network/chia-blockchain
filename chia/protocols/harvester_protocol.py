from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Tuple

from chia_rs import G1Element, G2Element

from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.reward_chain_block import RewardChainBlockUnfinished
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import int16, uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable

"""
Protocol between harvester and farmer.
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


@streamable
@dataclass(frozen=True)
class PoolDifficulty(Streamable):
    difficulty: uint64
    sub_slot_iters: uint64
    pool_contract_puzzle_hash: bytes32


@streamable
@dataclass(frozen=True)
class HarvesterHandshake(Streamable):
    farmer_public_keys: List[G1Element]
    pool_public_keys: List[G1Element]


@streamable
@dataclass(frozen=True)
class NewSignagePointHarvester(Streamable):
    challenge_hash: bytes32
    difficulty: uint64
    sub_slot_iters: uint64
    signage_point_index: uint8
    sp_hash: bytes32
    pool_difficulties: List[PoolDifficulty]
    filter_prefix_bits: uint8


@streamable
@dataclass(frozen=True)
class ProofOfSpaceFeeInfo(Streamable):
    applied_fee_threshold: uint32


@streamable
@dataclass(frozen=True)
class NewProofOfSpace(Streamable):
    challenge_hash: bytes32
    sp_hash: bytes32
    plot_identifier: str
    proof: ProofOfSpace
    signage_point_index: uint8
    include_source_signature_data: bool
    farmer_reward_address_override: Optional[bytes32]
    fee_info: Optional[ProofOfSpaceFeeInfo]


# Source data corresponding to the hash that is sent to the Harvester for signing
class SigningDataKind(IntEnum):
    FOLIAGE_BLOCK_DATA = 1
    FOLIAGE_TRANSACTION_BLOCK = 2
    CHALLENGE_CHAIN_VDF = 3
    REWARD_CHAIN_VDF = 4
    CHALLENGE_CHAIN_SUB_SLOT = 5
    REWARD_CHAIN_SUB_SLOT = 6
    PARTIAL = 7


@streamable
@dataclass(frozen=True)
class SignatureRequestSourceData(Streamable):
    kind: uint8
    data: bytes


# message_data elements are optional as FoliageTransactionBlock may not always be present in
# the case of the UnfinishedBlock not being a transaction block.
@streamable
@dataclass(frozen=True)
class RequestSignatures(Streamable):
    plot_identifier: str
    challenge_hash: bytes32
    sp_hash: bytes32
    messages: List[bytes32]
    # This, and rc_block_unfinished are only set when using a third-party harvester (see CHIP-22)
    message_data: Optional[List[Optional[SignatureRequestSourceData]]]
    rc_block_unfinished: Optional[RewardChainBlockUnfinished]


@streamable
@dataclass(frozen=True)
class RespondSignatures(Streamable):
    plot_identifier: str
    challenge_hash: bytes32
    sp_hash: bytes32
    local_pk: G1Element
    farmer_pk: G1Element
    message_signatures: List[Tuple[bytes32, G2Element]]
    include_source_signature_data: bool
    farmer_reward_address_override: Optional[bytes32]


@streamable
@dataclass(frozen=True)
class Plot(Streamable):
    filename: str
    size: uint8
    plot_id: bytes32
    pool_public_key: Optional[G1Element]
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element
    file_size: uint64
    time_modified: uint64
    compression_level: Optional[uint8]


@streamable
@dataclass(frozen=True)
class RequestPlots(Streamable):
    pass


@streamable
@dataclass(frozen=True)
class RespondPlots(Streamable):
    plots: List[Plot]
    failed_to_open_filenames: List[str]
    no_key_filenames: List[str]


@streamable
@dataclass(frozen=True)
class PlotSyncIdentifier(Streamable):
    timestamp: uint64
    sync_id: uint64
    message_id: uint64


@streamable
@dataclass(frozen=True)
class PlotSyncStart(Streamable):
    identifier: PlotSyncIdentifier
    initial: bool
    last_sync_id: uint64
    plot_file_count: uint32
    harvesting_mode: uint8

    def __str__(self) -> str:
        return (
            f"PlotSyncStart: identifier {self.identifier}, initial {self.initial}, "
            f"last_sync_id {self.last_sync_id}, plot_file_count {self.plot_file_count}, "
            f"harvesting_mode {self.harvesting_mode}"
        )


@streamable
@dataclass(frozen=True)
class PlotSyncPathList(Streamable):
    identifier: PlotSyncIdentifier
    data: List[str]
    final: bool

    def __str__(self) -> str:
        return f"PlotSyncPathList: identifier {self.identifier}, count {len(self.data)}, final {self.final}"


@streamable
@dataclass(frozen=True)
class PlotSyncPlotList(Streamable):
    identifier: PlotSyncIdentifier
    data: List[Plot]
    final: bool

    def __str__(self) -> str:
        return f"PlotSyncPlotList: identifier {self.identifier}, count {len(self.data)}, final {self.final}"


@streamable
@dataclass(frozen=True)
class PlotSyncDone(Streamable):
    identifier: PlotSyncIdentifier
    duration: uint64

    def __str__(self) -> str:
        return f"PlotSyncDone: identifier {self.identifier}, duration {self.duration}"


@streamable
@dataclass(frozen=True)
class PlotSyncError(Streamable):
    code: int16
    message: str
    expected_identifier: Optional[PlotSyncIdentifier]

    def __str__(self) -> str:
        return f"PlotSyncError: code {self.code}, count {self.message}, expected_identifier {self.expected_identifier}"


@streamable
@dataclass(frozen=True)
class PlotSyncResponse(Streamable):
    identifier: PlotSyncIdentifier
    message_type: int16
    error: Optional[PlotSyncError]

    def __str__(self) -> str:
        return f"PlotSyncResponse: identifier {self.identifier}, message_type {self.message_type}, error {self.error}"
