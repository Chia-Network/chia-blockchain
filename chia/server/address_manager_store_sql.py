from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Optional

import aiosqlite

from chia.server.address_manager import (
    AddressManager,
    ExtendedPeerInfo,
)
from chia.util.db_wrapper import DBWrapper2

Node = tuple[int, ExtendedPeerInfo]
Table = tuple[int, int]

log = logging.getLogger(__name__)


class AddressManagerStore:
    @classmethod
    async def initialise(cls, db_wrapper: DBWrapper2) -> None:
        async with db_wrapper.writer_maybe_transaction() as writer:
            await writer.execute("""
                CREATE TABLE IF NOT EXISTS peers (
                    node_id INTEGER PRIMARY KEY,
                    info TEXT,
                    is_tried BOOLEAN,
                    ref_count INTEGER,
                    bucket INTEGER
                )
            """)
            await writer.commit()

    @classmethod
    async def create_address_manager(cls, db_wrapper: DBWrapper2) -> AddressManager:
        """
        Creates an AddressManager using data from the SQLite peer db
        """
        return await cls.deserialize(db_wrapper)

    @staticmethod
    async def get_all_peers(db_wrapper: DBWrapper2) -> Iterable[aiosqlite.Row]:
        async with db_wrapper.writer() as writer:
            cursor = await writer.execute("SELECT * FROM peers")
            return await cursor.fetchall()

    @staticmethod
    async def add_peer(
        node_id: int, info: str, is_tried: bool, ref_count: int, bucket: Optional[int], db_wrapper: DBWrapper2
    ) -> None:
        async with db_wrapper.writer() as writer:
            await writer.execute(
                """
                INSERT INTO peers (node_id, info, is_tried, ref_count, bucket)
                VALUES (?, ?, ?, ?, ?)
                """,
                (node_id, info, is_tried, ref_count, bucket),
            )
            await writer.commit()

    @staticmethod
    async def remove_peer(node_id: int, db_wrapper: DBWrapper2) -> None:
        async with db_wrapper.writer() as writer:
            await writer.execute("DELETE FROM peers WHERE node_id = ?", (node_id,))
            await writer.commit()

    # TODO: deprecate this in favour of periodic calls to add_peer() and remove_peer()
    @classmethod
    async def serialize(cls, address_manager: AddressManager, db_wrapper: DBWrapper2) -> None:
        async with db_wrapper.writer() as writer:
            await writer.execute("DELETE FROM peers")
            await writer.commit()
        for node_id, info in address_manager.map_info.items():
            await cls.add_peer(node_id, str(info), info.is_tried, info.ref_count, None, db_wrapper)
        log.debug("Peer data serialized successfully")

    @classmethod
    async def deserialize(cls, db_wrapper: DBWrapper2) -> AddressManager:
        log.info("Deserializing peer data from database")
        address_manager = AddressManager()
        peers = await cls.get_all_peers(db_wrapper)
        for node_id, info_str, is_tried, ref_count, bucket in peers:
            info = ExtendedPeerInfo.from_string(info_str)
            info.is_tried = bool(is_tried)
            info.ref_count = ref_count
            address_manager.map_info[node_id] = info
        log.debug("Peer data deserialized successfully")
        return address_manager
