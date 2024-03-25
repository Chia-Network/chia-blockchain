from __future__ import annotations

from enum import IntEnum
from typing import TypeVar

from typing_extensions import Protocol

from chia.protocols.harvester_protocol import PlotSyncIdentifier


class Constants:
    message_timeout: int = 10


class State(IntEnum):
    idle = 0
    loaded = 1
    removed = 2
    invalid = 3
    keys_missing = 4
    duplicates = 5
    done = 6


class ErrorCodes(IntEnum):
    unknown = -1
    invalid_state = 0
    invalid_peer_id = 1
    invalid_identifier = 2
    invalid_last_sync_id = 3
    invalid_connection_type = 4
    plot_already_available = 5
    plot_not_available = 6
    sync_ids_match = 7


class PlotSyncMessage(Protocol):
    @property
    def identifier(self) -> PlotSyncIdentifier:
        pass


T_PlotSyncMessage = TypeVar("T_PlotSyncMessage", bound=PlotSyncMessage)
