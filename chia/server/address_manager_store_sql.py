from __future__ import annotations

import logging
from typing import Optional

import aiosqlite

from chia.server.address_manager import (
    AddressManager,
    ExtendedPeerInfo,
)

Node = tuple[int, ExtendedPeerInfo]
Table = tuple[int, int]

log = logging.getLogger(__name__)


class AddressManagerStore:
    @classmethod
    async def initialise(cls, connection) -> None:
        await connection.execute("""
                CREATE TABLE IF NOT EXISTS peers (
                    node_id INTEGER PRIMARY KEY,
                    info TEXT,
                    is_tried BOOLEAN,
                    ref_count INTEGER,
                    bucket INTEGER
                )
            """)
        await connection.commit()

    @classmethod
    async def create_address_manager(cls, connection: aiosqlite.Connection) -> Optional[AddressManager]:
        """
        Creates an AddressManager using data from the SQLite peer db
        """
        return cls.deserialize(connection)

    @staticmethod
    async def get_all_peers(connection: aiosqlite.Connection) -> list[tuple[int, str, bool, int, Optional[int]]]:
        cursor = await connection.execute("SELECT * FROM peers")
        return await cursor.fetchall()

    @staticmethod
    async def add_peer(
        node_id: int, info: str, is_tried: bool, ref_count: int, bucket: Optional[int], connection: aiosqlite.Connection
    ) -> None:
        await connection.execute(
            """
            INSERT INTO peers (node_id, info, is_tried, ref_count, bucket)
            VALUES (?, ?, ?, ?, ?)
            """,
            (node_id, info, is_tried, ref_count, bucket),
        )
        await connection.commit()

    @staticmethod
    async def remove_peer(node_id: int, connection: aiosqlite.Connection) -> None:
        await connection.execute("DELETE FROM peers WHERE node_id = ?", (node_id,))
        await connection.commit()

    # TODO: deprecate this in favour of periodic calls to add_peer() and remove_peer() 
    @classmethod
    async def serialize(cls, address_manager: AddressManager, connection: aiosqlite.Connection) -> None:
        await connection.execute("DELETE FROM peers")
        await connection.commit()
        for node_id, info in address_manager.map_info.items():
            await cls.add_peer(node_id, str(info), info.is_tried, info.ref_count, None)
        log.debug("Peer data serialized successfully")

    @classmethod
    async def deserialize(cls, connection: aiosqlite.Connection) -> AddressManager:
        log.info("Deserializing peer data from database")
        address_manager = AddressManager()
        peers = await cls.get_all_peers(connection)
        for node_id, info_str, is_tried, ref_count, bucket in peers:
            info = ExtendedPeerInfo.from_string(info_str)
            info.is_tried = bool(is_tried)
            info.ref_count = ref_count
            address_manager.map_info[node_id] = info
        log.debug("Peer data deserialized successfully")
        return address_manager
