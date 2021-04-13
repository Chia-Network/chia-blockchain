import dataclasses
import time
from datetime import timedelta
from datetime import datetime
from typing import List, Optional

import aiosqlite

from src.crawler.peer_record import PeerRecord, PeerReliability
from src.types.peer_info import PeerInfo 
from pytz import timezone

def utc_to_eastern(date: datetime):
    date = date.replace(tzinfo=timezone("UTC"))
    date = date.astimezone(timezone("US/Eastern"))
    return date


def utc_timestamp():
    now = datetime.utcnow()
    now = now.replace(tzinfo=timezone("UTC"))
    return int(now.timestamp())

def utc_timestamp_to_eastern(timestamp: float):
    date = datetime.fromtimestamp(timestamp, tz=timezone("UTC"))
    eastern = date.astimezone(timezone("US/Eastern"))
    return eastern

def current_eastern_datetime():
    date = datetime.utcnow()
    date = date.replace(tzinfo=timezone("UTC"))
    eastern = date.astimezone(timezone("US/Eastern"))
    return eastern


def datetime_eastern_datetime(date):
    date = date.replace(tzinfo=timezone("UTC"))
    eastern = date.astimezone(timezone("US/Eastern"))
    return eastern


class CrawlStore:
    crawl_db: aiosqlite.Connection
    cached_peers: List[PeerRecord]
    last_timestamp: int
    lock: asyncio.Lock

    @classmethod
    async def create(cls, connection: aiosqlite.Connection):
        self = cls()

        self.crawl_db = connection
        await self.crawl_db.execute(
            (
                "CREATE TABLE IF NOT EXISTS peer_records("
                " peer_id text PRIMARY KEY,"
                " ip_address text,"
                " port bigint,"
                " connected int,"
                " last_try_timestamp bigint,"
                " try_count bigint,"
                " connected_timestamp bigint,"
                " added_timestamp bigint)"
            )
        )
        await self.crawl_db.execute(
            (
                "CREATE TABLE IF NOT EXISTS peer_reliability("
                " peer_id text PRIMARY KEY,"
                " ignore_till int,"
                " stat_2h_w real, stat_2h_c real, stat_2h_r real,"
                " stat_8h_w real, stat_8h_c real, stat_8h_r real,"
                " stat_1d_w real, stat_1d_c real, stat_1d_r real,"
                " stat_1w_w real, stat_1w_c real, stat_1w_r real,"
                " stat_1m_w real, stat_1m_c real, stat_1m_r real)"
            )
        )

        await self.crawl_db.execute(
            "CREATE INDEX IF NOT EXISTS ip_address on peer_records(ip_address)"
        )

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS port on peer_records(port)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS connected on peer_records(connected)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS added_timestamp on peer_records(added_timestamp)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS peer_id on peer_reliability(peer_id)")

        await self.crawl_db.commit()
        self.coin_record_cache = dict()
        self.cached_peers = []
        self.last_timestamp = 0
        self.lock = asyncio.Lock()
        return self

    async def add_peer(self, peer_record: PeerRecord, peer_reliability: PeerReliability):
        added_timestamp = utc_timestamp()
        cursor = await self.crawl_db.execute(
            "INSERT OR REPLACE INTO peer_records VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                peer_record.peer_id,
                peer_record.ip_address,
                peer_record.port,
                int(peer_record.connected),
                peer_record.last_try_timestamp,
                peer_record.try_count,
                peer_record.connected_timestamp,
                added_timestamp
            ),
        )
        await cursor.close()
        cursor = await self.crawl_db.execute(
            "INSERT OR REPLACE INTO peer_reliability VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                peer_reliability.peer_id,
                peer_reliability.ignore_till,
                peer_reliability.stat_2h.weight, peer_reliability.stat_2h.count, peer_reliability.stat_2h.reliability,
                peer_reliability.stat_8h.weight, peer_reliability.stat_8h.count, peer_reliability.stat_8h.reliability,
                peer_reliability.stat_1d.weight, peer_reliability.stat_1d.count, peer_reliability.stat_1d.reliability,
                peer_reliability.stat_1w.weight, peer_reliability.stat_1w.count, peer_reliability.stat_1w.reliability,
                peer_reliability.stat_1m.weight, peer_reliability.stat_1m.count, peer_reliability.stat_1m.reliability,  
            ),
        )
        await cursor.close()

    async def get_peer_reliability(self, peer_id: str) -> PeerReliability:
        cursor = await self.crawl_db.execute(
            f"SELECT * from peer_reliability WHERE peer_id=?",
            (peer_id),
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        reliability = PeerReliability(
            row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7],
            row[8], row[9], row[10], row[11], row[12], row[13], row[14], row[15], row[16],
        )
        return reliability

    async def delete_by_ip(self, ip):
        # Delete from storage
        c1 = await self.crawl_db.execute("DELETE FROM peer_records WHERE ip_address=?", (ip,))
        await c1.close()

    async def peer_tried_to_connect(self, peer: PeerRecord):
        now = utc_timestamp()
        replaced = dataclasses.replace(peer, try_count=peer.try_count+1, last_try_timestamp=now)
        reliability = await self.get_peer_reliability(peer.peer_id)
        reliability.update(False, now - peer.last_try_timestamp)
        await self.add_peer(replaced, reliability)

    async def peer_connected(self, peer: PeerRecord):
        now = utc_timestamp()
        replaced = dataclasses.replace(peer, connected=True, connected_timestamp=now)
        reliability = await self.get_peer_reliability(peer.peer_id)
        reliability.update(False, now - peer.last_try_timestamp)
        await self.add_peer(replaced, reliability)

    async def get_peers_today(self) -> List[PeerRecord]:
        now = utc_timestamp()
        start = utc_timestamp_to_eastern(now)
        start = start - timedelta(days=1)
        start = start.replace(hour=23, minute=59, second=59)
        start_timestamp = int(start.timestamp())
        cursor = await self.crawl_db.execute(
            f"SELECT * from peer_records WHERE added_timestamp>?",
            (start_timestamp,),
        )
        rows = await cursor.fetchall()
        peers = []
        await cursor.close()
        for row in rows:
            peer = PeerRecord(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
            peers.append(peer)
        return peers

    async def get_peer_by_ip(self, ip_address) -> Optional[PeerRecord]:
        cursor = await self.crawl_db.execute(
            f"SELECT * from peer_records WHERE ip_address=?",
            (ip_address,),
        )
        row = await cursor.fetchone()

        if row is not None:
            peer = PeerRecord(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
            return peer
        else:
            return None

    async def get_peers_today_not_connected(self):
        # now = utc_timestamp()
        # start = utc_timestamp_to_eastern(now)
        # start = start - timedelta(days=1)
        # start = start.replace(hour=23, minute=59, second=59)
        # start_timestamp = int(start.timestamp())
        cursor = await self.crawl_db.execute(
            f"SELECT * from peer_records WHERE connected=?",
            (0,),
        )
        rows = await cursor.fetchall()
        peers = []
        await cursor.close()
        for row in rows:
            peer = PeerRecord(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
            peers.append(peer)
        return peers

    async def get_peers_today_connected(self):
        now = utc_timestamp()
        start = utc_timestamp_to_eastern(now)
        start = start - timedelta(days=1)
        start = start.replace(hour=23, minute=59, second=59)
        start_timestamp = int(start.timestamp())
        cursor = await self.crawl_db.execute(
            f"SELECT * from peer_records WHERE connected_timestamp>? and connected=?",
            (start_timestamp,1,),
        )
        rows = await cursor.fetchall()
        peers = []
        await cursor.close()
        for row in rows:
            peer = PeerRecord(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
            peers.append(peer)
        return peers

    async def get_cached_peers(self, peer_count: int) -> List[PeerInfo]:
        now = utc_timestamp()
        peers = []
        async with self.lock:
            if now - self.last_timestamp > 180:
                cursor = await self.crawl_db.execute(
                    f"SELECT ip_address, port from peer_records WHERE connected=?",
                    (True),
                )
                rows = await cursor.fetchall()
                peers = []
                await cursor.close()
                for row in rows:
                    peer = PeerInfo(row[0], row[1])
                    peers.append(peer)
                self.cached_peers = peers
                self.last_timestamp = utc_timestamp()
            else:
                peers = self.cached_peers
        if len(peers) > peer_count:
            random.shuffle(peers)
            peers = peers[:peer_count]
        return peers

    async def get_peers_to_crawl(self, batch_size) -> List[PeerRecord]:
        peer_id = []
        now = utc_timestamp()
        cursor = await self.crawl_db.execute(
            f"SELECT * from peer_reliability WHERE ignore_till<?",
            (now),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            peer = PeerReliability(
                row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7],
                row[8], row[9], row[10], row[11], row[12], row[13], row[14], row[15], row[16],
            )
            if peer.is_reliable():
                peer_id.add(peer.peer_id)
        cursor = await self.crawl_db.execute(
            f"SELECT peer_id from peer_records WHERE last_try_timestamp=0",
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            peer_id.add(row[0])
        if len(peer_id) > batch_size:
            peer_id.shuffle()
            peer_id = peer_id[:batch_size]
        peers = []
        for id in peer_id:
            cursor = await self.crawl_db.execute(
                f"SELECT * from peer_records WHERE peer_id=?",
                (id),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            peer = PeerRecord(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
            peer.append(peers)
        return peers
