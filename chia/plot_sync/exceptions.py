from __future__ import annotations

from typing import Any

from chia.plot_sync.util import ErrorCodes, State
from chia.protocols.harvester_protocol import PlotSyncIdentifier
from chia.server.ws_connection import NodeType
from chia.util.ints import uint64


class PlotSyncException(Exception):
    def __init__(self, message: str, error_code: ErrorCodes) -> None:
        super().__init__(message)
        self.error_code = error_code


class AlreadyStartedError(Exception):
    def __init__(self) -> None:
        super().__init__("Already started!")


class InvalidValueError(PlotSyncException):
    def __init__(self, message: str, actual: Any, expected: Any, error_code: ErrorCodes) -> None:
        super().__init__(f"{message}: Actual {actual}, Expected {expected}", error_code)


class InvalidIdentifierError(InvalidValueError):
    def __init__(self, actual_identifier: PlotSyncIdentifier, expected_identifier: PlotSyncIdentifier) -> None:
        super().__init__("Invalid identifier", actual_identifier, expected_identifier, ErrorCodes.invalid_identifier)
        self.actual_identifier: PlotSyncIdentifier = actual_identifier
        self.expected_identifier: PlotSyncIdentifier = expected_identifier


class InvalidLastSyncIdError(InvalidValueError):
    def __init__(self, actual: uint64, expected: uint64) -> None:
        super().__init__("Invalid last-sync-id", actual, expected, ErrorCodes.invalid_last_sync_id)


class InvalidConnectionTypeError(InvalidValueError):
    def __init__(self, actual: NodeType, expected: NodeType) -> None:
        super().__init__("Unexpected connection type", actual, expected, ErrorCodes.invalid_connection_type)


class PlotAlreadyAvailableError(PlotSyncException):
    def __init__(self, state: State, path: str) -> None:
        super().__init__(f"{state.name}: Plot already available - {path}", ErrorCodes.plot_already_available)


class PlotNotAvailableError(PlotSyncException):
    def __init__(self, state: State, path: str) -> None:
        super().__init__(f"{state.name}: Plot not available - {path}", ErrorCodes.plot_not_available)


class SyncIdsMatchError(PlotSyncException):
    def __init__(self, state: State, sync_id: uint64) -> None:
        super().__init__(f"{state.name}: Sync ids are equal - {sync_id}", ErrorCodes.sync_ids_match)
