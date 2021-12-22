from chia.plot_sync.util import ErrorCodes, State
from chia.protocols.plot_sync_protocol import Identifier


class PlotSyncException(Exception):
    def __init__(self, message, error_code: ErrorCodes) -> None:
        super(PlotSyncException, self).__init__(message)
        self.error_code = error_code


class AlreadyStartedError(Exception):
    def __init__(self):
        super(AlreadyStartedError, self).__init__("Already started!")


class InvalidValueError(PlotSyncException):
    def __init__(self, message, actual, expected, error_code: ErrorCodes) -> None:
        super(InvalidValueError, self).__init__(f"{message}: Actual {actual}, Expected {expected}", error_code)


class InvalidIdentifierError(InvalidValueError):
    def __init__(self, actual_identifier: Identifier, expected_identifier: Identifier) -> None:
        super(InvalidIdentifierError, self).__init__(
            "Invalid identifier", actual_identifier, expected_identifier, ErrorCodes.invalid_identifier
        )
        self.actual_identifier: Identifier = actual_identifier
        self.expected_identifier: Identifier = expected_identifier


class InvalidLastSyncIdError(InvalidValueError):
    def __init__(self, actual, expected) -> None:
        super(InvalidLastSyncIdError, self).__init__(
            "Invalid last-sync-id", actual, expected, ErrorCodes.invalid_last_sync_id
        )


class InvalidConnectionTypeError(InvalidValueError):
    def __init__(self, actual, expected) -> None:
        super(InvalidConnectionTypeError, self).__init__(
            "Unexpected connection type", actual, expected, ErrorCodes.invalid_connection_type
        )


class PlotAlreadyAvailableError(PlotSyncException):
    def __init__(self, state: State, path: str) -> None:
        super(PlotAlreadyAvailableError, self).__init__(
            f"{state.name}: Plot already available - {path}", ErrorCodes.plot_already_available
        )


class PlotNotAvailableError(PlotSyncException):
    def __init__(self, state: State, path: str) -> None:
        super(PlotNotAvailableError, self).__init__(
            f"{state.name}: Plot not available - {path}", ErrorCodes.plot_not_available
        )


class SyncIdsMatchError(PlotSyncException):
    def __init__(self, state: State, match) -> None:
        super(SyncIdsMatchError, self).__init__(
            f"{state.name}: Sync ids are equal - {match}", ErrorCodes.sync_ids_match
        )
