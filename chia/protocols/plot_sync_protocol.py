from dataclasses import dataclass
from typing import List, Optional

from chia.protocols.harvester_protocol import Plot
from chia.util.ints import int16, uint32, uint64
from chia.util.streamable import Streamable, streamable

"""
Plot sync from peer A to peer B. Used to sync the plots from the harvester to the farmer.
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


@dataclass(frozen=True)
@streamable
class Identifier(Streamable):
    timestamp: uint64
    sync_id: uint64
    message_id: uint64


@dataclass(frozen=True)
@streamable
class Start(Streamable):
    identifier: Identifier
    initial: bool
    last_sync_id: uint64
    plot_file_count: uint32

    def __str__(self):
        return (
            f"Start: identifier {self.identifier}, initial {self.initial}, "
            f"last_sync_id {self.last_sync_id}, plot_file_count {self.plot_file_count}"
        )


@dataclass(frozen=True)
@streamable
class PathList(Streamable):
    identifier: Identifier
    data: List[str]
    final: bool

    def __str__(self):
        return f"PathList: identifier {self.identifier}, count {len(self.data)}, final {self.final}"


@dataclass(frozen=True)
@streamable
class PlotList(Streamable):
    identifier: Identifier
    data: List[Plot]
    final: bool

    def __str__(self):
        return f"PlotList: identifier {self.identifier}, count {len(self.data)}, final {self.final}"


@dataclass(frozen=True)
@streamable
class Done(Streamable):
    identifier: Identifier
    duration: uint64

    def __str__(self):
        return f"Done: identifier {self.identifier}, duration {self.duration}"


@dataclass(frozen=True)
@streamable
class Error(Streamable):
    code: int16
    message: str
    expected_identifier: Optional[Identifier]

    def __str__(self):
        return f"Error: code {self.code}, count {self.message}, expected_identifier {self.expected_identifier}"


@dataclass(frozen=True)
@streamable
class Response(Streamable):
    identifier: Identifier
    message_type: int16
    error: Optional[Error]

    def __str__(self):
        return f"Response: identifier {self.identifier}, message_type {self.message_type}, error {self.error}"
