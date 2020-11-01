from dataclasses import dataclass
from typing import List

from src.types.peer_info import TimestampedPeerInfo
from src.util.cbor_message import cbor_message


"""
Protocol to introducer
"""


@dataclass(frozen=True)
@cbor_message
class RequestPeers:
    """
    Return full list of peers
    """


@dataclass(frozen=True)
@cbor_message
class RespondPeers:
    peer_list: List[TimestampedPeerInfo]
