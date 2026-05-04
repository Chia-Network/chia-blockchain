from __future__ import annotations

import dataclasses

from chia_rs.sized_ints import uint8, uint16

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import ConfigureWindowSizes
from chia.util.errors import Err, ProtocolError


@dataclasses.dataclass
class RateLimitsV3:
    """
    In-flight window for each peer, for each supported protocol message type
    """

    # Number of requests currently being processed
    receive_window: int
    # Number of in-flight outbound requests
    in_flight: int


@dataclasses.dataclass(frozen=True)
class RLSettingsV3:
    # Maximum allowed number of in-flight requests per message type, `None`
    # means unlimited.
    window_size: int | None


# Message types tracked by v3 in-flight window, where both peers advertise
# RATE_LIMITS_V3 capability. If a message is in this list, it will not be
# subject to the time based rate limiter.
rate_limits_v3: dict[ProtocolMessageTypes, RLSettingsV3] = {
    ProtocolMessageTypes.request_blocks: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_blocks: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.reject_blocks: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.request_block: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_block: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.reject_block: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.request_block_header: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_block_header: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.reject_header_request: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.request_block_headers: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_block_headers: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.reject_block_headers: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.request_header_blocks: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_header_blocks: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.reject_header_blocks: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.register_for_ph_updates: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_to_ph_updates: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.register_for_coin_updates: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_to_coin_updates: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.request_puzzle_state: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_puzzle_state: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.reject_puzzle_state: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.request_coin_state: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_coin_state: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.reject_coin_state: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.request_additions: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_additions: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.reject_additions_request: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.request_removals: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_removals: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.reject_removals_request: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.request_proof_of_weight: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_proof_of_weight: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.request_puzzle_solution: RLSettingsV3(window_size=2),
    ProtocolMessageTypes.respond_puzzle_solution: RLSettingsV3(window_size=None),
    ProtocolMessageTypes.reject_puzzle_solution: RLSettingsV3(window_size=None),
}

# Maximum number of window sizes we allow to be set by the
# `ConfigureWindowSizes` message.
MAX_CONFIGURE_RATE_LIMITS_ENTRIES: int = 256


def rl_v3_to_configure_message(
    settings: dict[ProtocolMessageTypes, RLSettingsV3] | None = None,
) -> ConfigureWindowSizes:
    """
    Encode a set of rate limits into a `ConfigureWindowSizes` message. If
    `settings` is `None` use the current local defaults in `rate_limits_v3`.
    """
    if settings is None:
        settings = rate_limits_v3
    assert 0 < len(settings) <= MAX_CONFIGURE_RATE_LIMITS_ENTRIES
    message_settings: list[tuple[uint8, uint16]] = [
        (uint8(msg_type.value), uint16(0 if setting.window_size is None else setting.window_size))
        for msg_type, setting in settings.items()
    ]
    return ConfigureWindowSizes(settings=message_settings)


def rl_settings_v3_from_configure_message(msg: ConfigureWindowSizes) -> dict[ProtocolMessageTypes, RLSettingsV3]:
    """
    Parse a `ConfigureWindowSizes` message rate limit settings. The peer
    controls what is included so only the entries present in the message are
    considered. Unknown entries are silently skipped while invalid ones result
    in a `ProtocolError` exception.
    """
    result: dict[ProtocolMessageTypes, RLSettingsV3] = {}
    for msg_type_val, window_size in msg.settings:
        try:
            message_type = ProtocolMessageTypes(msg_type_val)
        except ValueError:
            continue
        # Don't allow peers to alter our unlimited (typically response type)
        # protocol messages windows.
        if message_type in rate_limits_v3 and rate_limits_v3[message_type].window_size is None and window_size != 0:
            raise ProtocolError(Err.INVALID_HANDSHAKE)
        result[message_type] = RLSettingsV3(window_size=None if window_size == 0 else window_size)
    return result
