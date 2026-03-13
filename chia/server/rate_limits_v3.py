from __future__ import annotations

import dataclasses

from chia_rs.sized_ints import uint16

from chia.protocols.protocol_message_types import ProtocolMessageTypes


@dataclasses.dataclass
class RateLimitsV3:
    """
    In-flight window for each peer, for each supported protocol message type
    """

    # Number of requests currently being processed
    receive_window: int
    # Number of in-flight outbound requests
    congestion_window: int


@dataclasses.dataclass(frozen=True)
class RLSettingsV3:
    # Limits the number of concurrently in-flight requests per message type
    window_size: int
    max_message_size: int


# Message types tracked by v3 in-flight window, where both peers advertise
# RATE_LIMITS_V3 capability. If a message is in this list, it will not be
# subject to the time based rate limiter.
# NOTE: When you add another entry, please review `MAX_RL_V3_CONFIG_STRING_BYTES`
# below in case it needs to grow accordingly.
rate_limits_v3: dict[ProtocolMessageTypes, RLSettingsV3] = {
    ProtocolMessageTypes.request_blocks: RLSettingsV3(window_size=3, max_message_size=100),
    ProtocolMessageTypes.request_block: RLSettingsV3(window_size=3, max_message_size=100),
    ProtocolMessageTypes.request_block_header: RLSettingsV3(window_size=3, max_message_size=100),
    ProtocolMessageTypes.request_block_headers: RLSettingsV3(window_size=3, max_message_size=100),
    ProtocolMessageTypes.request_header_blocks: RLSettingsV3(window_size=3, max_message_size=100),
    ProtocolMessageTypes.request_proof_of_weight: RLSettingsV3(window_size=1, max_message_size=100),
    ProtocolMessageTypes.request_transaction: RLSettingsV3(window_size=10, max_message_size=100),
    ProtocolMessageTypes.register_for_ph_updates: RLSettingsV3(window_size=3, max_message_size=100 * 1024 * 1024),
    ProtocolMessageTypes.register_for_coin_updates: RLSettingsV3(window_size=3, max_message_size=100 * 1024 * 1024),
    ProtocolMessageTypes.request_puzzle_state: RLSettingsV3(window_size=1, max_message_size=100 * 1024 * 1024),
    ProtocolMessageTypes.request_coin_state: RLSettingsV3(window_size=3, max_message_size=100 * 1024 * 1024),
}

# Maximum number of bytes we will accept for the RATE_LIMITS_V3 capability
# value in the handshake.
MAX_RL_V3_CONFIG_STRING_BYTES: int = 256


def rl_v3_to_capability_string() -> str:
    # Format each entry as "<msg_type_value>:<window_size>:<max_message_size>"
    return ",".join(
        f"{message_type.value}:{rl_settings_v3.window_size}:{rl_settings_v3.max_message_size}"
        for message_type, rl_settings_v3 in rate_limits_v3.items()
    )


def rl_settings_v3_from_capabilities(
    raw_capabilities: list[tuple[uint16, str]],
) -> dict[ProtocolMessageTypes, RLSettingsV3]:
    """
    Extract rate limit v3 settings from the handshake capabilities list.
    The relevant string is expected to be a comma separated list of
    `<msg_type>:<max_concurrent>:<msg_size>` entries. Malformed entries are
    silently ignored.
    """
    from chia.protocols.shared_protocol import Capability

    for capability_id, value in raw_capabilities:
        if capability_id != Capability.RATE_LIMITS_V3.value:
            continue
        if value == "0":
            # Explicitly disabled v3 capability
            return {}
        # Start with a copy of our global defaults and peers may send us a
        # subset or override values. This way we ensure that all v3 supported
        # message types get populated.
        result: dict[ProtocolMessageTypes, RLSettingsV3] = dict(rate_limits_v3)
        for entry in value.split(","):
            parts = entry.split(":")
            if len(parts) != 3:
                continue
            # Any failure here skips the entry
            try:
                message_type_val = int(parts[0])
                window_size = int(parts[1])
                max_message_size = int(parts[2])
                message_type = ProtocolMessageTypes(message_type_val)
            except ValueError:
                continue
            # Only override known message types so we ignore unknown ones
            if message_type in result and window_size >= 1 and max_message_size >= 1:
                result[message_type] = RLSettingsV3(window_size=window_size, max_message_size=max_message_size)
        return result
    # No capability advertised
    return {}
