import asyncio
import dataclasses
import ipaddress
import logging
import random
import time
from databases import Database
from typing import List, Dict

from chia.seeder.peer_record import PeerRecord, PeerReliability
from chia.util import dialect_utils

log = logging.getLogger(__name__)


class CrawlStore:
    crawl_db: Database
    last_timestamp: int
    lock: asyncio.Lock

    host_to_records: Dict
    host_to_selected_time: Dict
    host_to_reliability: Dict
    banned_peers: int
    ignored_peers: int
    reliable_peers: int

    @classmethod
    async def create(cls, connection: Database):
        self = cls()

        self.crawl_db = connection
        async with self.crawl_db.connection() as connection:
            async with connection.transaction():
                await self.crawl_db.execute(
                    (
                        "CREATE TABLE IF NOT EXISTS peer_records("
                        f" peer_id {dialect_utils.data_type('text-as-index', self.crawl_db.url.dialect)} PRIMARY KEY,"
                        f" ip_address {dialect_utils.data_type('text-as-index', self.crawl_db.url.dialect)},"
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
                )
                await self.crawl_db.execute(
                    (
                        "CREATE TABLE IF NOT EXISTS peer_reliability("
                        f" peer_id {dialect_utils.data_type('text-as-index', self.crawl_db.url.dialect)} PRIMARY KEY,"
                        " ignore_till int, ban_till int,"
                        " stat_2h_w real, stat_2h_c real, stat_2h_r real,"
                        " stat_8h_w real, stat_8h_c real, stat_8h_r real,"
                        " stat_1d_w real, stat_1d_c real, stat_1d_r real,"
                        " stat_1w_w real, stat_1w_c real, stat_1w_r real,"
                        " stat_1m_w real, stat_1m_c real, stat_1m_r real,"
                        " tries int, successes int)"
                    )
                )

                try:
                    await self.crawl_db.execute("ALTER TABLE peer_records ADD COLUMN tls_version text")
                except:
                    pass  # ignore what is likely Duplicate column error

                await self.crawl_db.execute(f"CREATE TABLE IF NOT EXISTS good_peers(ip {dialect_utils.data_type('text-as-index', self.crawl_db.url.dialect)})")

                await dialect_utils.create_index_if_not_exists(self.crawl_db, 'ip_address', 'peer_records', ['ip_address'])

                await dialect_utils.create_index_if_not_exists(self.crawl_db, 'port', 'peer_records', ['port'])

                await dialect_utils.create_index_if_not_exists(self.crawl_db, 'connected', 'peer_records', ['connected'])

                await dialect_utils.create_index_if_not_exists(self.crawl_db, 'added_timestamp', 'peer_records', ['added_timestamp'])

                await dialect_utils.create_index_if_not_exists(self.crawl_db, 'peer_id', 'peer_reliability', ['peer_id'])
                await dialect_utils.create_index_if_not_exists(self.crawl_db, 'ignore_till', 'peer_reliability', ['ignore_till'])

        self.last_timestamp = 0
        self.ignored_peers = 0
        self.banned_peers = 0
        self.reliable_peers = 0
        self.host_to_selected_time = {}
        await self.unload_from_db()
        return self

    def maybe_add_peer(self, peer_record: PeerRecord, peer_reliability: PeerReliability):
        if peer_record.peer_id not in self.host_to_records:
            self.host_to_records[peer_record.peer_id] = peer_record
        if peer_reliability.peer_id not in self.host_to_reliability:
            self.host_to_reliability[peer_reliability.peer_id] = peer_reliability

    async def add_peer(self, peer_record: PeerRecord, peer_reliability: PeerReliability, save_db: bool = False):
        if not save_db:
            self.host_to_records[peer_record.peer_id] = peer_record
            self.host_to_reliability[peer_reliability.peer_id] = peer_reliability
            return

        added_timestamp = int(time.time())
        row_to_insert = {
            "peer_id": peer_record.peer_id,
            "ip_address": peer_record.ip_address,
            "port": int(peer_record.port),
            "connected": int(peer_record.connected),
            "last_try_timestamp": int(peer_record.last_try_timestamp),
            "try_count": int(peer_record.try_count),
            "connected_timestamp": int(peer_record.connected_timestamp),
            "added_timestamp": int(added_timestamp),
            "best_timestamp": int(peer_record.best_timestamp),
            "version": peer_record.version,
            "handshake_time": int(peer_record.handshake_time),
            "tls_version": peer_record.tls_version,
        }
        await self.crawl_db.execute(
            dialect_utils.upsert_query('peer_records', ['peer_id'], row_to_insert.keys(), self.crawl_db.url.dialect),
            row_to_insert
        )
        row_to_insert = {
            "peer_id": peer_reliability.peer_id,
            "ignore_till": peer_reliability.ignore_till,
            "ban_till": peer_reliability.ban_till,
            "stat_2h_w": peer_reliability.stat_2h.weight,
            "stat_2h_c": peer_reliability.stat_2h.count,
            "stat_2h_r": peer_reliability.stat_2h.reliability,
            "stat_8h_w": peer_reliability.stat_8h.weight,
            "stat_8h_c": peer_reliability.stat_8h.count,
            "stat_8h_r": peer_reliability.stat_8h.reliability,
            "stat_1d_w": peer_reliability.stat_1d.weight,
            "stat_1d_c": peer_reliability.stat_1d.count,
            "stat_1d_r": peer_reliability.stat_1d.reliability,
            "stat_1w_w": peer_reliability.stat_1w.weight,
            "stat_1w_c": peer_reliability.stat_1w.count,
            "stat_1w_r": peer_reliability.stat_1w.reliability,
            "stat_1m_w": peer_reliability.stat_1m.weight,
            "stat_1m_c": peer_reliability.stat_1m.count,
            "stat_1m_r": peer_reliability.stat_1m.reliability,
            "tries": peer_reliability.tries,
            "successes": peer_reliability.successes,
        },
        await self.crawl_db.execute(
            dialect_utils.upsert_query('peer_reliability', ['peer_id'], row_to_insert.keys(), self.crawl_db.url.dialect),
            row_to_insert
        )


    async def get_peer_reliability(self, peer_id: str) -> PeerReliability:
        return self.host_to_reliability[peer_id]

    async def peer_failed_to_connect(self, peer: PeerRecord):
        now = int(time.time())
        age_timestamp = int(max(peer.last_try_timestamp, peer.connected_timestamp))
        if age_timestamp == 0:
            age_timestamp = now - 1000
        replaced = dataclasses.replace(peer, try_count=peer.try_count + 1, last_try_timestamp=now)
        reliability = await self.get_peer_reliability(peer.peer_id)
        if reliability is None:
            reliability = PeerReliability(peer.peer_id)
        reliability.update(False, now - age_timestamp)
        await self.add_peer(replaced, reliability)

    async def peer_connected(self, peer: PeerRecord, tls_version: str):
        now = int(time.time())
        age_timestamp = int(max(peer.last_try_timestamp, peer.connected_timestamp))
        if age_timestamp == 0:
            age_timestamp = now - 1000
        replaced = dataclasses.replace(peer, connected=True, connected_timestamp=now, tls_version=tls_version)
        reliability = await self.get_peer_reliability(peer.peer_id)
        if reliability is None:
            reliability = PeerReliability(peer.peer_id)
        reliability.update(True, now - age_timestamp)
        await self.add_peer(replaced, reliability)

    async def update_best_timestamp(self, host: str, timestamp):
        if host not in self.host_to_records:
            return
        record = self.host_to_records[host]
        replaced = dataclasses.replace(record, best_timestamp=timestamp)
        if host not in self.host_to_reliability:
            return
        reliability = self.host_to_reliability[host]
        await self.add_peer(replaced, reliability)

    async def peer_connected_hostname(self, host: str, connected: bool = True, tls_version: str = "unknown"):
        if host not in self.host_to_records:
            return
        record = self.host_to_records[host]
        if connected:
            await self.peer_connected(record, tls_version)
        else:
            await self.peer_failed_to_connect(record)

    async def get_peers_to_crawl(self, min_batch_size, max_batch_size) -> List[PeerRecord]:
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

    async def load_to_db(self):
        log.error("Saving peers to DB...")
        async with self.crawl_db.connection() as connection:
            async with connection.transaction():
                for peer_id in list(self.host_to_reliability.keys()):
                    if peer_id in self.host_to_reliability and peer_id in self.host_to_records:
                        reliability = self.host_to_reliability[peer_id]
                        record = self.host_to_records[peer_id]
                        await self.add_peer(record, reliability, True)
        log.error(" - Done saving peers to DB")

    async def unload_from_db(self):
        self.host_to_records = {}
        self.host_to_reliability = {}
        log.error("Loading peer reliability records...")
        rows = await self.crawl_db.fetch_all(
            "SELECT * from peer_reliability",
        )

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
            self.host_to_reliability[row[0]] = reliability
        log.error("  - Done loading peer reliability records...")
        log.error("Loading peer records...")
        rows = await self.crawl_db.fetch_all(
            "SELECT * from peer_records",
        )
        for row in rows:
            peer = PeerRecord(
                row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10], row[11]
            )
            self.host_to_records[row[0]] = peer
        log.error("  - Done loading peer records...")

    # Crawler -> DNS.
    async def load_reliable_peers_to_db(self):
        peers = []
        for peer_id in self.host_to_reliability:
            reliability = self.host_to_reliability[peer_id]
            if reliability.is_reliable():
                peers.append(peer_id)
        self.reliable_peers = len(peers)
        log.error("Deleting old good_peers from DB...")
        async with self.crawl_db.connection() as connection:
            async with connection.transaction():
                await self.crawl_db.execute(
                    "DELETE from good_peers",
                )

                log.error(" - Done deleting old good_peers...")
                log.error("Saving new good_peers to DB...")
                for peer in peers:
                    await self.crawl_db.execute(
                        "INSERT INTO good_peers VALUES(:peer)",
                        {"peer": peer},
                    )
                log.error(" - Done saving new good_peers to DB...")

    def load_host_to_version(self):
        versions = {}
        handshake = {}

        for host, record in self.host_to_records.items():
            if host not in self.host_to_records:
                continue
            record = self.host_to_records[host]
            if record.version == "undefined":
                continue
            versions[host] = record.version
            handshake[host] = record.handshake_time

        return (versions, handshake)

    def load_best_peer_reliability(self):
        best_timestamp = {}
        for host, record in self.host_to_records.items():
            best_timestamp[host] = record.best_timestamp
        return best_timestamp

    async def update_version(self, host, version, now):
        record = self.host_to_records.get(host, None)
        reliability = self.host_to_reliability.get(host, None)
        if record is None or reliability is None:
            return
        record.update_version(version, now)
        await self.add_peer(record, reliability)
