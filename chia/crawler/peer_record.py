from dataclasses import dataclass
from src.util.ints import uint32, uint64
from src.util.streamable import Streamable, streamable
import math
import time
from datetime import timedelta
from datetime import datetime


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

class PeerStat:
    weight: float
    count: float
    reliability: float

    def __init__(self):
        weight = 0.0
        count = 0.0
        reliability = 0.0

    def update(self, is_reachable: bool, age: int, tau: int):
        f = math.exp(-age / tau)
        reliability = reliability * f + (1.0 - f if is_reachable else 0)
        count = count * f + 1
        weight = weight * f + 1.0 - f


class PeerReliability:
    peer_id: str
    ignore_till: int
    stat_2h: PeerStat
    stat_8h: PeerStat
    stat_1d: PeerStat
    stat_1w: PeerStat
    stat_1m: PeerStat

    def __init__(self, peer_id: str):
        self.peer_id = peer_id
        self.ignore_till = 0
        self.stat_2h = PeerStat()
        self.stat_8h = PeerStat()
        self.stat_1d = PeerStat()
        self.stat_1w = PeerStat()
        self.stat_1m = PeerStat()

    def is_reliable(self) -> bool:
        if self.stat_2h.reliability > 0.85 and self.stat_2h.count > 2:
            return True
        if self.stat_8h.reliability > 0.7 and self.stat_8h.count > 4:
            return True
        if self.stat_1d.reliability > 0.55 and self.stat_1d.count > 8:
            return True
        if self.stat_1w.reliability > 0.45 and self.stat_1w.count > 16:
            return True
        if self.stat_1m.reliability > 0.35 and self.stat_1m.count > 32:
            return True
        return False

    def get_ban_time(self) -> int:
        if self.is_reliable():
            return 0
        if self.stat_1m.reliability - self.stat_1m.weight + 1 < 0.15 and self.stat_1m.count > 32:
            return 30 * 86400
        if self.stat_1w.reliability - self.stat_1w.weight + 1.0 < 0.10 and self.stat_1w.count > 16:
            return 7 * 86400
        if self.stat_1d.reliability - self.stat_1d.weight + 1.0 < 0.05 and self.stat_1d.count > 8:
            return 86400
        return 0

    def get_ignore_time(self) -> int:
        if self.is_reliable():
            return 0
        if self.stat_1m.reliability - self.stat_1m.weight + 1.0 < 0.20 and self.stat_1m.count > 2:
            return 10 * 86400
        if self.stat_1w.reliability - self.stat_1w.weight + 1.0 < 0.16 and self.stat_1w.count > 2:
            return 3 * 86400
        if self.stat_1d.reliability - self.stat_1d.weight + 1.0 < 0.12 and self.stat_1d.count > 2:
            return 8 * 3600
        if self.stat_8h.reliability - self.stat_8h.weight + 1.0 < 0.08 and self.stat_8h.count > 2:
            return 2 * 3600
        return 0

    def update(self, is_reachable: bool, age: int):
        self.stat_2h.update(is_reachable, age, 2 * 3600)
        self.stat_8h.update(is_reachable, age, 8 * 3600)
        self.stat_1d.update(is_reachable, age, 24 * 3600)
        self.stat_1w.update(is_reachable, age, 7 * 24 * 3600)
        self.stat_1m.update(is_reachable, age, 24 * 30 * 3600)
        current_ignore_time = self.get_ignore_time()
        now = datetime.utcnow()
        now = now.replace(tzinfo=timezone("UTC"))
        return int(now.timestamp())
        if current_ignore_time > 0 and (self.ignore_till == 0 or self.ignore_till < current_ignore_time + now):
            self.ignore_till = current_ignore_time + now
