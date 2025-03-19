from __future__ import annotations

import logging

import aiosqlite

from chia.server.address_manager import (
    AddressManager,
    ExtendedPeerInfo,
)
from chia.server.address_manager_sql_shared import clear_peers, get_all_peers

Node = tuple[int, ExtendedPeerInfo]
Table = tuple[int, int]

log = logging.getLogger(__name__)


class AddressManagerStore:
    @classmethod
    async def initialise(cls, connection: aiosqlite.Connection) -> None:
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
    async def create_address_manager(cls, connection: aiosqlite.Connection) -> AddressManager:
        """
        Creates an AddressManager using data from the SQLite peer db
        """
        return await cls.deserialize(connection)

    # TODO: deprecate this in favour of periodic calls to add_peer() and remove_peer()
    @classmethod
    async def serialize(cls, address_manager: AddressManager, connection: aiosqlite.Connection) -> None:
        await clear_peers(connection)
        await connection.commit()
        for node_id, info in address_manager.map_info.items():
            await cls.add_peer(node_id, str(info), info.is_tried, info.ref_count, None, connection)
        log.debug("Peer data serialized successfully")

    @classmethod
    async def deserialize(cls, connection: aiosqlite.Connection) -> AddressManager:
        log.info("Deserializing peer data from database")
        address_manager = AddressManager()
        peers = await get_all_peers(connection)
        for node_id, info_str, is_tried, ref_count, bucket in peers:
            info = ExtendedPeerInfo.from_string(info_str)
            info.is_tried = bool(is_tried)
            info.ref_count = ref_count
            address_manager.map_info[node_id] = info
        log.debug("Peer data deserialized successfully")
        return address_manager
