from __future__ import annotations

import ipaddress
import logging
import random
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Dict, List

import aiosqlite

from chia.seeder.peer_record import PeerRecord, PeerReliability
from chia.util.ints import uint32, uint64

log = logging.getLogger(__name__)


@dataclass
class CrawlStore:
    crawl_db: aiosqlite.Connection
    host_to_records: Dict[str, PeerRecord] = field(default_factory=dict)  # peer_id: PeerRecord
    host_to_selected_time: Dict[str, float] = field(default_factory=dict)  # peer_id: timestamp (as a float)
    host_to_reliability: Dict[str, PeerReliability] = field(default_factory=dict)  # peer_id: PeerReliability
    banned_peers: int = 0
    ignored_peers: int = 0
    reliable_peers: int = 0

    @classmethod
    async def create(cls, connection: aiosqlite.Connection) -> CrawlStore:
        self = cls(connection)

        await self.crawl_db.execute(
            "CREATE TABLE IF NOT EXISTS peer_records("
            " peer_id text PRIMARY KEY,"
            " ip_address text,"
            " port bigint,"
            " connected int,"
            " last_try_timestamp bigint,"
            " try_count bigint,"
            " connected_timestamp bigint,"
            " added_timestamp bigint,"
            " best_timestamp bigint,"
            " version text,"
            " handshake_time text"
            " tls_version text)"
        )
        await self.crawl_db.execute(
            "CREATE TABLE IF NOT EXISTS peer_reliability("
            " peer_id text PRIMARY KEY,"
            " ignore_till int, ban_till int,"
            " stat_2h_w real, stat_2h_c real, stat_2h_r real,"
            " stat_8h_w real, stat_8h_c real, stat_8h_r real,"
            " stat_1d_w real, stat_1d_c real, stat_1d_r real,"
            " stat_1w_w real, stat_1w_c real, stat_1w_r real,"
            " stat_1m_w real, stat_1m_c real, stat_1m_r real,"
            " tries int, successes int)"
        )

        try:
            await self.crawl_db.execute("ALTER TABLE peer_records ADD COLUMN tls_version text")
        except aiosqlite.OperationalError:
            pass  # ignore what is likely Duplicate column error

        await self.crawl_db.execute("CREATE TABLE IF NOT EXISTS good_peers(ip text)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS ip_address on peer_records(ip_address)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS port on peer_records(port)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS connected on peer_records(connected)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS added_timestamp on peer_records(added_timestamp)")

        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS peer_id on peer_reliability(peer_id)")
        await self.crawl_db.execute("CREATE INDEX IF NOT EXISTS ignore_till on peer_reliability(ignore_till)")

        await self.crawl_db.commit()
        await self.unload_from_db()
        return self

    def maybe_add_peer(self, peer_record: PeerRecord, peer_reliability: PeerReliability) -> None:
        if peer_record.peer_id not in self.host_to_records:
            self.host_to_records[peer_record.peer_id] = peer_record
        if peer_reliability.peer_id not in self.host_to_reliability:
            self.host_to_reliability[peer_reliability.peer_id] = peer_reliability

    async def add_peer(self, peer_record: PeerRecord, peer_reliability: PeerReliability, save_db: bool = False) -> None:
        if not save_db:
            self.host_to_records[peer_record.peer_id] = peer_record
            self.host_to_reliability[peer_reliability.peer_id] = peer_reliability
            return

        added_timestamp = int(time.time())
        cursor = await self.crawl_db.execute(
            "INSERT OR REPLACE INTO peer_records VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                peer_record.peer_id,
                peer_record.ip_address,
                peer_record.port,
                int(peer_record.connected),
                peer_record.last_try_timestamp,
                peer_record.try_count,
                peer_record.connected_timestamp,
                added_timestamp,
                peer_record.best_timestamp,
                peer_record.version,
                peer_record.handshake_time,
                peer_record.tls_version,
            ),
        )
        await cursor.close()
        cursor = await self.crawl_db.execute(
            "INSERT OR REPLACE INTO peer_reliability"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                peer_reliability.peer_id,
                peer_reliability.ignore_till,
                peer_reliability.ban_till,
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
                peer_reliability.tries,
                peer_reliability.successes,
            ),
        )
        await cursor.close()

    async def get_peer_reliability(self, peer_id: str) -> PeerReliability:
        return self.host_to_reliability[peer_id]

    async def peer_failed_to_connect(self, peer: PeerRecord) -> None:
        now = uint64(time.time())
        age_timestamp = int(max(peer.last_try_timestamp, peer.connected_timestamp))
        if age_timestamp == 0:
            age_timestamp = now - 1000
        replaced = replace(peer, try_count=uint32(peer.try_count + 1), last_try_timestamp=now)
        reliability = await self.get_peer_reliability(peer.peer_id)
        if reliability is None:
            reliability = PeerReliability(peer.peer_id)
        reliability.update(False, now - age_timestamp)
        await self.add_peer(replaced, reliability)

    async def peer_connected(self, peer: PeerRecord, tls_version: str) -> None:
        now = uint64(time.time())
        age_timestamp = int(max(peer.last_try_timestamp, peer.connected_timestamp))
        if age_timestamp == 0:
            age_timestamp = now - 1000
        replaced = replace(peer, connected=True, connected_timestamp=now, tls_version=tls_version)
        reliability = await self.get_peer_reliability(peer.peer_id)
        if reliability is None:
            reliability = PeerReliability(peer.peer_id)
        reliability.update(True, now - age_timestamp)
        await self.add_peer(replaced, reliability)

    async def update_best_timestamp(self, host: str, timestamp: uint64) -> None:
        if host not in self.host_to_records:
            return
        record = self.host_to_records[host]
        replaced = replace(record, best_timestamp=timestamp)
        if host not in self.host_to_reliability:
            return
        reliability = self.host_to_reliability[host]
        await self.add_peer(replaced, reliability)

    async def peer_connected_hostname(self, host: str, connected: bool = True, tls_version: str = "unknown") -> None:
        if host not in self.host_to_records:
            return
        record = self.host_to_records[host]
        if connected:
            await self.peer_connected(record, tls_version)
        else:
            await self.peer_failed_to_connect(record)

    async def get_peers_to_crawl(self, min_batch_size: int, max_batch_size: int) -> List[PeerRecord]:
        now = int(time.time())
        records = []
        records_v6 = []
        counter = 0
        self.ignored_peers = 0
        self.banned_peers = 0
        for peer_id in self.host_to_reliability:
            add = False
            counter += 1
            reliability = self.host_to_reliability[peer_id]
            if reliability.ignore_till < now and reliability.ban_till < now:
                add = True
            else:
                if reliability.ban_till >= now:
                    self.banned_peers += 1
                elif reliability.ignore_till >= now:
                    self.ignored_peers += 1
            record = self.host_to_records[peer_id]
            if record.last_try_timestamp == 0 and record.connected_timestamp == 0:
                add = True
            if peer_id in self.host_to_selected_time:
                last_selected = self.host_to_selected_time[peer_id]
                if time.time() - last_selected < 120:
                    add = False
            if add:
                v6 = True
                try:
                    _ = ipaddress.IPv6Address(peer_id)
                except ValueError:
                    v6 = False
                delta_time = 600 if v6 else 1000
                if now - record.last_try_timestamp >= delta_time and now - record.connected_timestamp >= delta_time:
                    if not v6:
                        records.append(record)
                    else:
                        records_v6.append(record)

        batch_size = max(min_batch_size, len(records) // 10)
        batch_size = min(batch_size, max_batch_size)
        if len(records) > batch_size:
            random.shuffle(records)
            records = records[:batch_size]
        if len(records_v6) > batch_size:
            random.shuffle(records_v6)
            records_v6 = records_v6[:batch_size]
        records += records_v6
        for record in records:
            self.host_to_selected_time[record.peer_id] = time.time()
        return records

    def get_ipv6_peers(self) -> int:
        counter = 0
        for peer_id in self.host_to_reliability:
            v6 = True
            try:
                _ = ipaddress.IPv6Address(peer_id)
            except ValueError:
                v6 = False
            if v6:
                counter += 1
        return counter

    def get_total_records(self) -> int:
        return len(self.host_to_records)

    def get_ignored_peers(self) -> int:
        return self.ignored_peers

    def get_banned_peers(self) -> int:
        return self.banned_peers

    def get_reliable_peers(self) -> int:
        return self.reliable_peers

    async def load_to_db(self) -> None:
        log.warning("Saving peers to DB...")
        for peer_id in list(self.host_to_reliability.keys()):
            if peer_id in self.host_to_reliability and peer_id in self.host_to_records:
                reliability = self.host_to_reliability[peer_id]
                record = self.host_to_records[peer_id]
                await self.add_peer(record, reliability, True)
        await self.crawl_db.commit()
        log.warning(" - Done saving peers to DB")

    async def unload_from_db(self) -> None:
        self.host_to_records = {}
        self.host_to_reliability = {}
        log.warning("Loading peer reliability records...")
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
                row[17],
                row[18],
                row[19],
            )
            self.host_to_reliability[reliability.peer_id] = reliability
        log.warning("  - Done loading peer reliability records...")
        log.warning("Loading peer records...")
        cursor = await self.crawl_db.execute(
            "SELECT * from peer_records",
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            peer = PeerRecord(
                row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10], row[11]
            )
            self.host_to_records[peer.peer_id] = peer
        log.warning("  - Done loading peer records...")

    # Crawler -> DNS.
    async def load_reliable_peers_to_db(self) -> None:
        peers = []
        for peer_id, reliability in self.host_to_reliability.items():
            if reliability.is_reliable():
                peers.append(peer_id)
        self.reliable_peers = len(peers)
        log.warning("Deleting old good_peers from DB...")
        cursor = await self.crawl_db.execute(
            "DELETE from good_peers",
        )
        await cursor.close()
        log.warning(" - Done deleting old good_peers...")
        log.warning("Saving new good_peers to DB...")
        for peer_id in peers:
            cursor = await self.crawl_db.execute(
                "INSERT OR REPLACE INTO good_peers VALUES(?)",
                (peer_id,),
            )
            await cursor.close()
        await self.crawl_db.commit()
        log.warning(" - Done saving new good_peers to DB...")

    def load_host_to_version(self) -> tuple[dict[str, str], dict[str, uint64]]:
        versions = {}
        handshake = {}

        for host, record in self.host_to_records.items():
            if host not in self.host_to_records:
                continue
            record = self.host_to_records[host]
            if record.version == "undefined":
                continue
            if record.handshake_time < time.time() - 5 * 24 * 3600:
                continue
            versions[host] = record.version
            handshake[host] = record.handshake_time

        return versions, handshake

    def load_best_peer_reliability(self) -> dict[str, uint64]:
        best_timestamp = {}
        for host, record in self.host_to_records.items():
            if record.best_timestamp > time.time() - 5 * 24 * 3600:
                best_timestamp[host] = record.best_timestamp
        return best_timestamp

    async def update_version(self, host: str, version: str, timestamp_now: uint64) -> None:
        record = self.host_to_records.get(host, None)
        reliability = self.host_to_reliability.get(host, None)
        if record is None or reliability is None:
            return
        record.update_version(version, timestamp_now)
        await self.add_peer(record, reliability)

    async def get_good_peers(self) -> list[str]:  # This is for the DNS server
        cursor = await self.crawl_db.execute(
            "SELECT * from good_peers",
        )
        rows = await cursor.fetchall()
        await cursor.close()
        result = [row[0] for row in rows]
        if len(result) > 0:
            random.shuffle(result)  # mix up the peers
        return result

    async def prune_old_peers(self, older_than_days: int) -> None:
        cutoff = int((datetime.now() - timedelta(days=older_than_days)).timestamp())

        # Deletes the old records from the DB
        await self.crawl_db.execute("delete from peer_records where best_timestamp < ?", (cutoff,))
        await self.crawl_db.execute(
            """
            delete from peer_reliability
            where not exists (
                select peer_records.peer_id
                from peer_records
                where peer_records.peer_id = peer_reliability.peer_id
            )
            """
        )
        await self.crawl_db.execute(
            """
            delete from good_peers
            where not exists (
                select peer_records.ip_address
                from peer_records
                where peer_records.ip_address = good_peers.ip
            )
            """
        )
        await self.crawl_db.commit()
        await self.crawl_db.execute("VACUUM")

        to_delete: List[str] = []

        # Deletes the old records from the in memory Dicts
        for peer_id, peer_record in self.host_to_records.items():
            if peer_record.best_timestamp < cutoff:
                to_delete.append(peer_id)

        for peer_id in to_delete:
            del self.host_to_records[peer_id]

            if peer_id in self.host_to_selected_time:
                del self.host_to_selected_time[peer_id]

            if peer_id in self.host_to_reliability:
                del self.host_to_reliability[peer_id]
