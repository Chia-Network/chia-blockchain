import time
from datetime import timedelta
from datetime import datetime
from typing import List, Optional

import aiosqlite

from src.crawler.peer_record import PeerRecord
from pytz import timezone

def utc_to_eastern(date: datetime):
    date = date.replace(tzinfo=timezone("UTC"))
    date = date.astimezone(timezone("US/Eastern"))
    return date


def utc_timestamp():
    now = datetime.utcnow()
    now = now.replace(tzinfo=timezone("UTC"))
    return now.timestamp()

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
            "CREATE INDEX IF NOT EXISTS ip_address on peer_records(ip_address)"
        )

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS port on peer_records(port)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS connected on peer_records(connected)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS added_timestamp on peer_records(added_timestamp)")

        await self.crawl_db.commit()
        self.coin_record_cache = dict()
        return self

    async def add_peer(self, peer_record: PeerRecord):
        added_timestamp = int(time.time())
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
            f"SELECT * from peer_records WHERE ip_address>?",
            (ip_address,),
        )
        row = await cursor.fetchone()

        if row is not None:
            peer = PeerRecord(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
            return peer
        else:
            return None

    async def get_peers_today_not_connected(self):
        now = utc_timestamp()
        start = utc_timestamp_to_eastern(now)
        start = start - timedelta(days=1)
        start = start.replace(hour=23, minute=59, second=59)
        start_timestamp = int(start.timestamp())
        cursor = await self.crawl_db.execute(
            f"SELECT * from peer_records WHERE added_timestamp>? and connected=?",
            (start_timestamp,0,),
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
            f"SELECT * from peer_records WHERE added_timestamp>? and connected=?",
            (start_timestamp,1,),
        )
        rows = await cursor.fetchall()
        peers = []
        await cursor.close()
        for row in rows:
            peer = PeerRecord(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
            peers.append(peer)
        return peers
