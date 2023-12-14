from __future__ import annotations

import logging
import sqlite3
from typing import List, Set

from chia.types.blockchain_format.sized_bytes import bytes32

log = logging.getLogger(__name__)


class PeerSubscriptions:
    _db_conn: sqlite3.Connection

    def __init__(self) -> None:
        self._db_conn = sqlite3.connect(":memory:")

        with self._db_conn as conn:
            log.info("DB: Creating peer subscription tables")
            conn.execute(
                """
                CREATE TABLE puzzle_subscriptions (
                    peer_id BLOB,
                    puzzle_hash BLOB,
                    UNIQUE (peer_id, puzzle_hash)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE coin_subscriptions (
                    peer_id BLOB,
                    coin_id BLOB,
                    UNIQUE (peer_id, coin_id)
                )
                """
            )

    def __del__(self) -> None:
        self._db_conn.close()

    def is_puzzle_subscribed(self, puzzle_hash: bytes32) -> bool:
        with self._db_conn as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM puzzle_subscriptions WHERE puzzle_hash=?", (puzzle_hash,)
            ).fetchone()

        assert row is not None

        return int(row[0]) > 0

    def is_coin_subscribed(self, coin_id: bytes32) -> bool:
        with self._db_conn as conn:
            row = conn.execute("SELECT COUNT(*) FROM coin_subscriptions WHERE coin_id=?", (coin_id,)).fetchone()

        assert row is not None

        return int(row[0]) > 0

    def _add_subscriptions(
        self, peer_id: bytes32, table_name: str, item_name: str, items: List[bytes32], max_items: int
    ) -> Set[bytes32]:
        existing_sub_count = self.peer_subscription_count(peer_id)
        inserted: Set[bytes32] = set()

        # If we've reached the subscription limit, just bail.
        if existing_sub_count >= max_items:
            log.info(
                "Peer %s reached the subscription limit. Not all coin states will be reported.",
                peer_id,
            )
            return inserted

        with self._db_conn as conn:
            # Decrement this counter as we go, to know if we've hit the subscription limit.
            subscriptions_left = max_items - existing_sub_count

            for item in items:
                try:
                    cursor = conn.execute(
                        f"INSERT INTO {table_name} (peer_id, {item_name}) VALUES (?, ?)", (peer_id, item)
                    )
                except sqlite3.Error:
                    continue

                if cursor.rowcount == 0:
                    continue

                inserted.add(item)
                subscriptions_left -= 1

                if subscriptions_left == 0:
                    log.info(
                        "Peer %s reached the subscription limit. Not all coin states will be reported.",
                        peer_id,
                    )
                    break

            return inserted

    def add_puzzle_subscriptions(self, peer_id: bytes32, puzzle_hashes: List[bytes32], max_items: int) -> Set[bytes32]:
        """
        Returns the items that were actually subscribed to, which is fewer in these cases:
        * There are duplicate items.
        * Some items are already subscribed to.
        * The `max_items` limit is exceeded.
        """
        return self._add_subscriptions(
            peer_id=peer_id,
            table_name="puzzle_subscriptions",
            item_name="puzzle_hash",
            items=puzzle_hashes,
            max_items=max_items,
        )

    def add_coin_subscriptions(self, peer_id: bytes32, coin_ids: List[bytes32], max_items: int) -> Set[bytes32]:
        """
        Returns the items that were actually subscribed to, which is fewer in these cases:
        * There are duplicate items.
        * Some items are already subscribed to.
        * The `max_items` limit is exceeded.
        """
        return self._add_subscriptions(
            peer_id=peer_id,
            table_name="coin_subscriptions",
            item_name="coin_id",
            items=coin_ids,
            max_items=max_items,
        )

    def peer_subscription_count(self, peer_id: bytes32) -> int:
        with self._db_conn as conn:
            row = conn.execute("SELECT COUNT(*) FROM puzzle_subscriptions WHERE peer_id=?", (peer_id,)).fetchone()
            assert row is not None
            puzzle_subscription_count = int(row[0])

            row = conn.execute("SELECT COUNT(*) FROM coin_subscriptions WHERE peer_id=?", (peer_id,)).fetchone()
            assert row is not None
            coin_subscription_count = int(row[0])

        return puzzle_subscription_count + coin_subscription_count

    def total_puzzle_subscriptions(self) -> int:
        with self._db_conn as conn:
            row = conn.execute("SELECT COUNT(*) FROM puzzle_subscriptions").fetchone()
            assert row is not None
            puzzle_subscription_count = int(row[0])

        return puzzle_subscription_count

    def total_coin_subscriptions(self) -> int:
        with self._db_conn as conn:
            row = conn.execute("SELECT COUNT(*) FROM coin_subscriptions").fetchone()
            assert row is not None
            coin_subscription_count = int(row[0])

        return coin_subscription_count

    def remove_peer(self, peer_id: bytes32) -> None:
        with self._db_conn as conn:
            conn.execute("DELETE FROM puzzle_subscriptions WHERE peer_id=?", (peer_id,))
            conn.execute("DELETE FROM coin_subscriptions WHERE peer_id=?", (peer_id,))

    def peers_for_coin_id(self, coin_id: bytes32) -> Set[bytes32]:
        with self._db_conn as conn:
            rows = conn.execute("SELECT peer_id FROM coin_subscriptions WHERE coin_id=?", (coin_id,)).fetchall()

        return {bytes32(row[0]) for row in rows}

    def peers_for_puzzle_hash(self, puzzle_hash: bytes32) -> Set[bytes32]:
        with self._db_conn as conn:
            rows = conn.execute(
                "SELECT peer_id FROM puzzle_subscriptions WHERE puzzle_hash=?", (puzzle_hash,)
            ).fetchall()

        return {bytes32(row[0]) for row in rows}
