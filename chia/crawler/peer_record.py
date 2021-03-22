from dataclasses import dataclass
from src.util.ints import uint32, uint64
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class PeerRecord(Streamable):
    peer_id: str
    ip_address: str
    port: uint32
    connected: bool
    last_try_timestamp: uint64
    try_count: uint32
    connected_timestamp: uint64
    added_timestamp: uint64
