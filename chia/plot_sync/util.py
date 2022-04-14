from enum import IntEnum


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
