from dataclasses import dataclass
from typing import List, Tuple, Optional

from blspy import G1Element, G2Element

from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import int16, uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable

"""
Protocol between harvester and farmer.
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


@dataclass(frozen=True)
@streamable
class PoolDifficulty(Streamable):
    difficulty: uint64
    sub_slot_iters: uint64
    pool_contract_puzzle_hash: bytes32


@dataclass(frozen=True)
@streamable
class HarvesterHandshake(Streamable):
    farmer_public_keys: List[G1Element]
    pool_public_keys: List[G1Element]


@dataclass(frozen=True)
@streamable
class NewSignagePointHarvester(Streamable):
    challenge_hash: bytes32
    difficulty: uint64
    sub_slot_iters: uint64
    signage_point_index: uint8
    sp_hash: bytes32
    pool_difficulties: List[PoolDifficulty]


@dataclass(frozen=True)
@streamable
class NewProofOfSpace(Streamable):
    challenge_hash: bytes32
    sp_hash: bytes32
    plot_identifier: str
    proof: ProofOfSpace
    signage_point_index: uint8


@dataclass(frozen=True)
@streamable
class RequestSignatures(Streamable):
    plot_identifier: str
    challenge_hash: bytes32
    sp_hash: bytes32
    messages: List[bytes32]


@dataclass(frozen=True)
@streamable
class RespondSignatures(Streamable):
    plot_identifier: str
    challenge_hash: bytes32
    sp_hash: bytes32
    local_pk: G1Element
    farmer_pk: G1Element
    message_signatures: List[Tuple[bytes32, G2Element]]


@dataclass(frozen=True)
@streamable
class Plot(Streamable):
    filename: str
    size: uint8
    plot_id: bytes32
    pool_public_key: Optional[G1Element]
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element
    file_size: uint64
    time_modified: uint64


@dataclass(frozen=True)
@streamable
class RequestPlots(Streamable):
    pass


@dataclass(frozen=True)
@streamable
class RespondPlots(Streamable):
    plots: List[Plot]
    failed_to_open_filenames: List[str]
    no_key_filenames: List[str]


@dataclass(frozen=True)
@streamable
class PlotSyncIdentifier(Streamable):
    timestamp: uint64
    sync_id: uint64
    message_id: uint64


@dataclass(frozen=True)
@streamable
class PlotSyncStart(Streamable):
    identifier: PlotSyncIdentifier
    initial: bool
    last_sync_id: uint64
    plot_file_count: uint32

    def __str__(self):
        return (
            f"PlotSyncStart: identifier {self.identifier}, initial {self.initial}, "
            f"last_sync_id {self.last_sync_id}, plot_file_count {self.plot_file_count}"
        )


@dataclass(frozen=True)
@streamable
class PlotSyncPathList(Streamable):
    identifier: PlotSyncIdentifier
    data: List[str]
    final: bool

    def __str__(self):
        return f"PlotSyncPathList: identifier {self.identifier}, count {len(self.data)}, final {self.final}"


@dataclass(frozen=True)
@streamable
class PlotSyncPlotList(Streamable):
    identifier: PlotSyncIdentifier
    data: List[Plot]
    final: bool

    def __str__(self):
        return f"PlotSyncPlotList: identifier {self.identifier}, count {len(self.data)}, final {self.final}"


@dataclass(frozen=True)
@streamable
class PlotSyncDone(Streamable):
    identifier: PlotSyncIdentifier
    duration: uint64

    def __str__(self):
        return f"PlotSyncDone: identifier {self.identifier}, duration {self.duration}"


@dataclass(frozen=True)
@streamable
class PlotSyncError(Streamable):
    code: int16
    message: str
    expected_identifier: Optional[PlotSyncIdentifier]

    def __str__(self):
        return f"PlotSyncError: code {self.code}, count {self.message}, expected_identifier {self.expected_identifier}"


@dataclass(frozen=True)
@streamable
class PlotSyncResponse(Streamable):
    identifier: PlotSyncIdentifier
    message_type: int16
    error: Optional[PlotSyncError]

    def __str__(self):
        return f"PlotSyncResponse: identifier {self.identifier}, message_type {self.message_type}, error {self.error}"
