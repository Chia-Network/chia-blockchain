from __future__ import annotations

import math
import time
from dataclasses import dataclass

from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class PeerRecord(Streamable):
    peer_id: str
    ip_address: str
    port: uint32
    connected: bool
    last_try_timestamp: uint64
    try_count: uint32
    connected_timestamp: uint64
    added_timestamp: uint64
    best_timestamp: uint64
    version: str
    handshake_time: uint64
    tls_version: str

    def update_version(self, version, now):
        if version != "undefined":
            object.__setattr__(self, "version", version)
        object.__setattr__(self, "handshake_time", uint64(now))


class PeerStat:
    weight: float
    count: float
    reliability: float

    def __init__(self, weight, count, reliability):
        self.weight = weight
        self.count = count
        self.reliability = reliability

    def update(self, is_reachable: bool, age: int, tau: int):
        f = math.exp(-age / tau)
        self.reliability = self.reliability * f + (1.0 - f if is_reachable else 0.0)
        self.count = self.count * f + 1.0
        self.weight = self.weight * f + 1.0 - f


class PeerReliability:
    peer_id: str
    ignore_till: int
    ban_till: int
    stat_2h: PeerStat
    stat_8h: PeerStat
    stat_1d: PeerStat
    stat_1w: PeerStat
    stat_1m: PeerStat
    tries: int
    successes: int

    def __init__(
        self,
        peer_id: str,
        ignore_till: int = 0,
        ban_till: int = 0,
        stat_2h_weight: float = 0.0,
        stat_2h_count: float = 0.0,
        stat_2h_reliability: float = 0.0,
        stat_8h_weight: float = 0.0,
        stat_8h_count: float = 0.0,
        stat_8h_reliability: float = 0.0,
        stat_1d_weight: float = 0.0,
        stat_1d_count: float = 0.0,
        stat_1d_reliability: float = 0.0,
        stat_1w_weight: float = 0.0,
        stat_1w_count: float = 0.0,
        stat_1w_reliability: float = 0.0,
        stat_1m_weight: float = 0.0,
        stat_1m_count: float = 0.0,
        stat_1m_reliability: float = 0.0,
        tries: int = 0,
        successes: int = 0,
    ):
        self.peer_id = peer_id
        self.ignore_till = ignore_till
        self.ban_till = ban_till
        self.stat_2h = PeerStat(stat_2h_weight, stat_2h_count, stat_2h_reliability)
        self.stat_8h = PeerStat(stat_8h_weight, stat_8h_count, stat_8h_reliability)
        self.stat_1d = PeerStat(stat_1d_weight, stat_1d_count, stat_1d_reliability)
        self.stat_1w = PeerStat(stat_1w_weight, stat_1w_count, stat_1w_reliability)
        self.stat_1m = PeerStat(stat_1m_weight, stat_1m_count, stat_1m_reliability)
        self.tries = tries
        self.successes = successes

    def is_reliable(self) -> bool:
        if self.tries > 0 and self.tries <= 3 and self.successes * 2 >= self.tries:
            return True
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
        self.tries += 1
        if is_reachable:
            self.successes += 1
        current_ignore_time = self.get_ignore_time()
        now = int(time.time())
        if current_ignore_time > 0 and (self.ignore_till == 0 or self.ignore_till < current_ignore_time + now):
            self.ignore_till = current_ignore_time + now
        current_ban_time = self.get_ban_time()
        if current_ban_time > 0 and (self.ban_till == 0 or self.ban_till < current_ban_time + now):
            self.ban_till = current_ban_time + now
