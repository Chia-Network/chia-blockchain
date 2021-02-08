from dataclasses import dataclass
from typing import List

from src.types.peer_info import TimestampedPeerInfo
from src.util.streamable import streamable, Streamable

"""
Protocol to introducer
Note: When changing this file, also change protocol_message_types.py, and the protocol version in shared_protocol.py
"""


@dataclass(frozen=True)
@streamable
class RequestPeersIntroducer(Streamable):
    """
    Return full list of peers
    """


@dataclass(frozen=True)
@streamable
class RespondPeersIntroducer(Streamable):
    peer_list: List[TimestampedPeerInfo]
