import dataclasses
import asyncio
import random
import logging
from datetime import timedelta
from datetime import datetime
from typing import List, Dict

import aiosqlite

from src.crawler.peer_record import PeerRecord, PeerReliability
from src.types.peer_info import PeerInfo
from pytz import timezone

log = logging.getLogger(__name__)


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

    host_to_records: Dict
    host_to_reliability: Dict

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
                " stat_1m_w real, stat_1m_c real, stat_1m_r real, is_reliable int)"
            )
        )

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS ip_address on peer_records(ip_address)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS port on peer_records(port)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS connected on peer_records(connected)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS added_timestamp on peer_records(added_timestamp)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS peer_id on peer_reliability(peer_id)")
        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS ignore_till on peer_reliability(ignore_till)")
        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS is_reliable on peer_reliability(is_reliable)")

        await self.crawl_db.commit()
        self.cached_peers = []
        self.last_timestamp = 0
        await self.unload_from_db()
        return self

    async def add_peer(self, peer_record: PeerRecord, peer_reliability: PeerReliability, save_db: bool = False):
        if not save_db:
            self.host_to_records[peer_record.peer_id] = peer_record
            self.host_to_reliability[peer_reliability.peer_id] = peer_reliability
            return

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
                added_timestamp,
            ),
        )
        await cursor.close()
        cursor = await self.crawl_db.execute(
            "INSERT OR REPLACE INTO peer_reliability VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                peer_reliability.peer_id,
                peer_reliability.ignore_till,
                peer_reliability.stat_2h.weight,
                peer_reliability.stat_2h.count,
                peer_reliability.stat_2h.reliability,
                peer_reliability.stat_8h.weight,
                peer_reliability.stat_8h.count,
                peer_reliability.stat_8h.reliability,
                peer_reliability.stat_1d.weight,
                peer_reliability.stat_1d.count,
                peer_reliability.stat_1d.reliability,
                peer_reliability.stat_1w.weight,
                peer_reliability.stat_1w.count,
                peer_reliability.stat_1w.reliability,
                peer_reliability.stat_1m.weight,
                peer_reliability.stat_1m.count,
                peer_reliability.stat_1m.reliability,
                int(peer_reliability.is_reliable()),
            ),
        )
        await cursor.close()

    async def get_peer_reliability(self, peer_id: str) -> PeerReliability:
        return self.host_to_reliability[peer_id]

    async def peer_tried_to_connect(self, peer: PeerRecord):
        now = utc_timestamp()
        replaced = dataclasses.replace(peer, try_count=peer.try_count + 1, last_try_timestamp=now)
        reliability = await self.get_peer_reliability(peer.peer_id)
        if reliability is None:
            reliability = PeerReliability(peer.peer_id)
        reliability.update(False, now - peer.last_try_timestamp)
        await self.add_peer(replaced, reliability)

    async def peer_connected(self, peer: PeerRecord):
        now = utc_timestamp()
        replaced = dataclasses.replace(peer, connected=True, connected_timestamp=now)
        reliability = await self.get_peer_reliability(peer.peer_id)
        if reliability is None:
            reliability = PeerReliability(peer.peer_id)
        reliability.update(True, now - peer.last_try_timestamp)
        await self.add_peer(replaced, reliability)

    async def peer_connected_hostname(self, host: str):
        if host not in self.host_to_records:
            return
        record = self.host_to_records[host]
        await self.peer_connected(record)

    async def get_peers_today_connected(self):
        now = utc_timestamp()
        start = utc_timestamp_to_eastern(now)
        start = start - timedelta(days=1)
        start = start.replace(hour=23, minute=59, second=59)
        start_timestamp = int(start.timestamp())
        counter = 0
        tries = 0
        for peer_id in self.host_to_records:
            record = self.host_to_records[peer_id]
            if record.connected_timestamp > start_timestamp and record.connected:
                counter += 1
            tries += 1
            if tries % 50000 == 0:
                await asyncio.sleep(0.1)
        return counter

    async def reload_cached_peers(self):
        peers = []
        counter = 0
        for peer_id in self.host_to_reliability:
            counter += 1
            reliability = self.host_to_reliability[peer_id]
            if reliability.is_reliable():
                peer = PeerInfo(peer_id, 8444)
                peers.append(peer)
            # Switch to responding some DNS queries.
            if counter % 50000 == 0:
                await asyncio.sleep(0.1)
        self.cached_peers = peers

    async def get_cached_peers(self, peer_count: int) -> List[PeerRecord]:
        peers = self.cached_peers
        if len(peers) > peer_count:
            random.shuffle(peers)
            peers = peers[:peer_count]
        return peers

    async def get_peers_to_crawl(self, batch_size) -> List[PeerRecord]:
        now = int(utc_timestamp())
        records = []
        counter = 0
        for peer_id in self.host_to_reliability:
            add = False
            counter += 1
            reliability = self.host_to_reliability[peer_id]
            if reliability.ignore_till < now and reliability.get_ban_time() < now:
                add = True
            record = self.host_to_records[peer_id]
            if record.last_try_timestamp == 0 and record.connected_timestamp == 0:
                add = True
            if add:
                records.append(record)
            # Switch to responding some DNS queries.
            if counter % 50000 == 0:
                await asyncio.sleep(0.1)
        if len(records) > batch_size:
            random.shuffle(records)
            records = records[:batch_size]
        return records

    async def load_to_db(self):
        counter = 0
        for peer_id in list(self.host_to_reliability.keys()):
            counter += 1
            if counter % 50000 == 0:
                await asyncio.sleep(0.1)
            if peer_id in self.host_to_reliability and peer_id in self.host_to_records:
                reliability = self.host_to_reliability[peer_id]
                record = self.host_to_records[peer_id]
                await self.add_peer(record, reliability, True)
        await self.crawl_db.commit()

    async def unload_from_db(self):
        self.host_to_records = {}
        self.host_to_reliability = {}
        cursor = await self.crawl_db.execute(
            "SELECT * from peer_reliability",
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            reliability = PeerReliability(
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
                row[10],
                row[11],
                row[12],
                row[13],
                row[14],
                row[15],
                row[16],
            )
            self.host_to_reliability[row[0]] = reliability
        cursor = await self.crawl_db.execute(
            "SELECT * from peer_records",
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            peer = PeerRecord(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
            self.host_to_records[row[0]] = peer
