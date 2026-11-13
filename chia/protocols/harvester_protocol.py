from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import BinaryIO, Self

from chia_rs import G1Element, G2Element, PartialProof, PlotParam, ProofOfSpace, RewardChainBlockUnfinished
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import int16, uint8, uint16, uint32, uint64
from packaging.version import Version

from chia.util.streamable import Streamable, streamable

"""
Protocol between harvester and farmer.
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""

LEGACY_PLOT_SERIALIZATION_VERSION = Version("0.0.37")
PLOT_GROUP_SERIALIZATION_VERSION = Version("0.0.39")


def supports_plot_groups(version: Version) -> bool:
    return version >= PLOT_GROUP_SERIALIZATION_VERSION


def supports_legacy_plot_serialization(version: Version) -> bool:
    return version <= LEGACY_PLOT_SERIALIZATION_VERSION


@streamable
@dataclass(frozen=True)
class PoolDifficulty(Streamable):
    difficulty: uint64
    sub_slot_iters: uint64
    pool_contract_puzzle_hash: bytes32


@streamable
@dataclass(frozen=True)
class HarvesterHandshake(Streamable):
    farmer_public_keys: list[G1Element]
    pool_public_keys: list[G1Element]


@streamable
@dataclass(frozen=True)
class NewSignagePointHarvester(Streamable):
    challenge_hash: bytes32
    difficulty: uint64
    sub_slot_iters: uint64
    signage_point_index: uint8
    sp_hash: bytes32
    pool_difficulties: list[PoolDifficulty]
    filter_prefix_bits: uint8


# this message has the same message ID as NewSignagePointHarvester, but this
# message format is used if the protocol version is 0.0.39 or higher.
@streamable
@dataclass(frozen=True)
class NewSignagePointHarvester2(Streamable):
    challenge_hash: bytes32
    difficulty: uint64
    sub_slot_iters: uint64
    signage_point_index: uint8
    sp_hash: bytes32
    pool_difficulties: list[PoolDifficulty]
    peak_height: uint32
    last_tx_height: uint32
    # V2 filter challenge from completed sub-slot history:
    # SPs [0-15] use SS(n-2); SPs [16-63] use SS(n-1).
    filter_challenge: bytes32 | None = None


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
    farmer_reward_address_override: bytes32 | None
    fee_info: ProofOfSpaceFeeInfo | None


@streamable
@dataclass(frozen=True)
class PartialProofsData(Streamable):
    challenge_hash: bytes32
    sp_hash: bytes32
    plot_identifier: str
    partial_proofs: list[PartialProof]
    signage_point_index: uint8
    plot_size: uint8
    plot_index: uint16
    meta_group: uint8
    strength: uint8
    plot_group_id: bytes32
    pool_public_key: G1Element | None
    pool_contract_puzzle_hash: bytes32 | None
    plot_public_key: G1Element


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
    messages: list[bytes32]
    # This, and rc_block_unfinished are only set when using a third-party harvester (see CHIP-22)
    message_data: list[SignatureRequestSourceData | None] | None
    rc_block_unfinished: RewardChainBlockUnfinished | None


@streamable
@dataclass(frozen=True)
class RespondSignatures(Streamable):
    plot_identifier: str
    challenge_hash: bytes32
    sp_hash: bytes32
    local_pk: G1Element
    farmer_pk: G1Element
    message_signatures: list[tuple[bytes32, G2Element]]
    include_source_signature_data: bool
    farmer_reward_address_override: bytes32 | None


@streamable
@dataclass(frozen=True)
class Plot(Streamable):
    # Field names are exposed by the farmer's get_harvester_plots_valid RPC; renaming them affects its API.
    filename: str
    # Legacy peers support V1 plots only; this field is the V1 k-size.
    size: uint8
    plot_id: bytes32
    pool_public_key: G1Element | None
    pool_contract_puzzle_hash: bytes32 | None
    plot_public_key: G1Element
    file_size: uint64
    time_modified: uint64
    compression_level: uint8 | None

    def param(self) -> PlotParam:
        if self.size & 0x80:
            raise ValueError("Legacy Plot serialization only supports V1 plots")
        return PlotParam.make_v1(self.size)

    def to_plot2(self) -> Plot2:
        self.param()
        # Legacy peers without compression support report None for uncompressed plots.
        return Plot2(
            filename=self.filename,
            pool_public_key=self.pool_public_key,
            pool_contract_puzzle_hash=self.pool_contract_puzzle_hash,
            plot_public_key=self.plot_public_key,
            file_size=self.file_size,
            time_modified=self.time_modified,
            size=self.size,
            plot_id=self.plot_id,
            compression_level=self.compression_level if self.compression_level is not None else uint8(0),
            group_plot_id=None,
            strength=None,
            meta_group=None,
            group_size=None,
        )


@streamable
@dataclass(frozen=True)
class Plot2(Streamable):
    # Field names are exposed by the farmer's get_harvester_plots_valid RPC; renaming them affects its API.
    # Plot2 represents V1 plots and V2 plot groups with separate fields.
    filename: str
    pool_public_key: G1Element | None
    pool_contract_puzzle_hash: bytes32 | None
    plot_public_key: G1Element
    file_size: uint64
    time_modified: uint64

    # V1 plot fields
    size: uint8 | None
    plot_id: bytes32 | None
    compression_level: uint8 | None

    # V2 plot group fields
    group_plot_id: bytes32 | None
    strength: uint8 | None
    meta_group: uint8 | None
    group_size: uint16 | None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.validate()

    @classmethod
    def parse(cls, f: BinaryIO, list_limits: dict[str, int] | None = None) -> Self:
        plot = super().parse(f, list_limits=list_limits)
        plot.validate()
        return plot

    def validate(self) -> None:
        v1_fields = (self.size, self.plot_id, self.compression_level)
        v2_fields = (self.group_plot_id, self.strength, self.meta_group, self.group_size)
        if self.strength is None:
            if any(field is None for field in v1_fields) or any(field is not None for field in v2_fields):
                raise ValueError("V1 Plot2 entries require size, plot_id, and compression_level only")
        elif (
            any(field is not None for field in v1_fields)
            or any(field is None for field in v2_fields)
            or self.group_size == 0
        ):
            raise ValueError("V2 Plot2 entries require group_plot_id, strength, meta_group, and positive group_size")

    def param(self) -> PlotParam:
        self.validate()
        if self.strength is not None:
            assert self.meta_group is not None
            return PlotParam.make_v2(0, self.meta_group, self.strength)

        assert self.size is not None
        return PlotParam.make_v1(self.size)


@streamable
@dataclass(frozen=True)
class RequestPlots(Streamable):
    pass


@streamable
@dataclass(frozen=True)
class RespondPlots(Streamable):
    plots: list[Plot]
    failed_to_open_filenames: list[str]
    no_key_filenames: list[str]


@streamable
@dataclass(frozen=True)
class RespondPlots2(Streamable):
    plots: list[Plot2]
    failed_to_open_filenames: list[str]
    no_key_filenames: list[str]


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
    data: list[str]
    final: bool

    def __str__(self) -> str:
        return f"PlotSyncPathList: identifier {self.identifier}, count {len(self.data)}, final {self.final}"


@streamable
@dataclass(frozen=True)
class PlotSyncPlotList(Streamable):
    identifier: PlotSyncIdentifier
    data: list[Plot]
    final: bool

    def __str__(self) -> str:
        return f"PlotSyncPlotList: identifier {self.identifier}, count {len(self.data)}, final {self.final}"


@streamable
@dataclass(frozen=True)
class PlotSyncPlotList2(Streamable):
    identifier: PlotSyncIdentifier
    data: list[Plot2]
    final: bool

    def __str__(self) -> str:
        return f"PlotSyncPlotList2: identifier {self.identifier}, count {len(self.data)}, final {self.final}"


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
    expected_identifier: PlotSyncIdentifier | None

    def __str__(self) -> str:
        return f"PlotSyncError: code {self.code}, count {self.message}, expected_identifier {self.expected_identifier}"


@streamable
@dataclass(frozen=True)
class PlotSyncResponse(Streamable):
    identifier: PlotSyncIdentifier
    message_type: int16
    error: PlotSyncError | None

    def __str__(self) -> str:
        return f"PlotSyncResponse: identifier {self.identifier}, message_type {self.message_type}, error {self.error}"
