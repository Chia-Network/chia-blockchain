from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import List, Set, final

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2

log = logging.getLogger(__name__)


@final
@dataclass
class PeerSubscriptions:
    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls) -> PeerSubscriptions:
        unique_database_uri = (
            f"file:db_{cls.__module__}.{cls.__qualname__}_{random.randint(0, 99999999)}?mode=memory&cache=shared"
        )
        db_wrapper = await DBWrapper2.create(database=unique_database_uri)
        self = PeerSubscriptions(db_wrapper)

        async with self.db_wrapper.writer() as conn:
            log.info("DB: Creating peer subscription tables")
            await conn.execute(
                """
                CREATE TABLE puzzle_subscriptions (
                    id INT PRIMARY KEY,
                    peer_id BLOB,
                    puzzle_hash BLOB,
                    UNIQUE (peer_id, puzzle_hash)
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE coin_subscriptions (
                    id INT PRIMARY KEY,
                    peer_id BLOB,
                    coin_id BLOB,
                    UNIQUE (peer_id, coin_id)
                )
                """
            )

        return self

    async def is_puzzle_subscribed(self, puzzle_hash: bytes32) -> bool:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM puzzle_subscriptions WHERE puzzle_hash=?", (puzzle_hash,)
            ) as cursor:
                row = await cursor.fetchone()

        assert row is not None

        return int(row[0]) > 0

    async def is_coin_subscribed(self, coin_id: bytes32) -> bool:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT COUNT(*) FROM coin_subscriptions WHERE coin_id=?", (coin_id,)) as cursor:
                row = await cursor.fetchone()

        assert row is not None

        return int(row[0]) > 0

    async def add_puzzle_subscriptions(
        self, peer_id: bytes32, puzzle_hashes: List[bytes32], max_items: int
    ) -> Set[bytes32]:
        """
        returns the puzzle hashes that were actually subscribed to. These may be
        fewer than requested in case:
        * there are duplicate puzzle_hashes
        * some puzzle hashes are already subscribed to
        * the max_items limit is exceeded
        """

        async with self.db_wrapper.writer() as conn:
            async with conn.execute("SELECT COUNT(*) FROM puzzle_subscriptions WHERE peer_id=?", (peer_id,)) as cursor:
                row = await cursor.fetchone()

            assert row is not None

            existing_sub_count = int(row[0])
            inserted: Set[bytes32] = set()

            # if we've reached the limit on number of subscriptions, just bail
            if existing_sub_count >= max_items:
                log.info(
                    "peer_id: %s reached max number of puzzle-hash subscriptions. "
                    "Not all its coin states will be reported",
                    peer_id,
                )
                return inserted

            # decrement this counter as we go, to know if we've hit the limit of
            # number of subscriptions
            subscriptions_left = max_items - existing_sub_count

            for puzzle_hash in puzzle_hashes:
                async with conn.execute(
                    "SELECT COUNT(*) FROM puzzle_subscriptions WHERE peer_id=? AND puzzle_hash=?",
                    (peer_id, puzzle_hash),
                ) as cursor:
                    row = await cursor.fetchone()

                assert row is not None

                if int(row[0]) > 0:
                    continue

                await conn.execute(
                    "INSERT INTO puzzle_subscriptions (peer_id, puzzle_hash) VALUES (?, ?)", (peer_id, puzzle_hash)
                )
                inserted.add(puzzle_hash)
                subscriptions_left -= 1

                if subscriptions_left == 0:
                    log.info(
                        "peer_id: %s reached max number of puzzle-hash subscriptions. "
                        "Not all its coin states will be reported",
                        peer_id,
                    )
                    break

            return inserted

    async def add_coin_subscriptions(self, peer_id: bytes32, coin_ids: List[bytes32], max_items: int) -> None:
        return None

    async def remove_puzzle_subscriptions(self, peer_id: bytes32, puzzle_hashes: List[bytes32]) -> None:
        return None

    async def remove_coin_subscriptions(self, peer_id: bytes32, coin_ids: List[bytes32]) -> None:
        return None

    async def remove_peer(self, peer_id: bytes32) -> None:
        async with self.db_wrapper.writer() as conn:
            await conn.execute("DELETE FROM puzzle_subscriptions WHERE peer_id=?", (peer_id,))
            await conn.execute("DELETE FROM coin_subscriptions WHERE peer_id=?", (peer_id,))

    async def peers_for_coin_id(self, coin_id: bytes32) -> Set[bytes32]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT peer_id FROM coin_subscriptions WHERE coin_id=?", (coin_id,)) as cursor:
                rows = await cursor.fetchall()

        return {bytes32(row[0]) for row in rows}

    async def peers_for_puzzle_hash(self, puzzle_hash: bytes32) -> Set[bytes32]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT peer_id FROM puzzle_subscriptions WHERE puzzle_hash=?", (puzzle_hash,)
            ) as cursor:
                rows = await cursor.fetchall()

        return {bytes32(row[0]) for row in rows}
