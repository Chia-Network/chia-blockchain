from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Tuple

from chia.util.ints import int16, uint8, uint16
from chia.util.streamable import Streamable, streamable

protocol_version = "0.0.35"


"""
Handshake when establishing a connection between two servers.
Note: When changing this file, also change protocol_message_types.py
"""


# Capabilities can be added here when new features are added to the protocol
# These are passed in as uint16 into the Handshake
class Capability(IntEnum):
    BASE = 1  # Base capability just means it supports the chia protocol at mainnet
    # introduces RequestBlockHeaders, which is a faster API for fetching header blocks
    # !! the old API is *RequestHeaderBlock* !!
    BLOCK_HEADERS = 2
    # Specifies support for v1 and v2 versions of rate limits. Peers will ues the lowest shared capability:
    # if peer A support v3 and peer B supports v2, they should send:
    # (BASE, RATE_LIMITS_V2, RATE_LIMITS_V3), and (BASE, RATE_LIMITS_V2) respectively. They will use the V2 limits.
    RATE_LIMITS_V2 = 3

    # a node can handle a None response and not wait the full timeout
    NONE_RESPONSE = 4


@streamable
@dataclass(frozen=True)
class Handshake(Streamable):
    network_id: str
    protocol_version: str
    software_version: str
    server_port: uint16
    node_type: uint8
    capabilities: List[Tuple[uint16, str]]


# "1" means capability is enabled
capabilities = [
    (uint16(Capability.BASE.value), "1"),
    (uint16(Capability.BLOCK_HEADERS.value), "1"),
    (uint16(Capability.RATE_LIMITS_V2.value), "1"),
    # (uint16(Capability.NONE_RESPONSE.value), "1"), # capability removed but functionality is still supported
]


@streamable
@dataclass(frozen=True)
class Error(Streamable):
    code: int16  # Err
    message: str
    data: Optional[bytes] = None
