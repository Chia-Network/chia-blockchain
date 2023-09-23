from __future__ import annotations

from dataclasses import dataclass
from typing import List

from chia.types.peer_info import TimestampedPeerInfo
from chia.util.streamable import Streamable, streamable

"""
Protocol to introducer
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


@streamable
@dataclass(frozen=True)
class RequestPeersIntroducer(Streamable):
    """
    Return full list of peers
    """


@streamable
@dataclass(frozen=True)
class RespondPeersIntroducer(Streamable):
    peer_list: List[TimestampedPeerInfo]
