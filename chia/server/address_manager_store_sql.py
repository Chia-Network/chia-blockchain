from __future__ import annotations

import logging

import aiosqlite

from chia.server.address_manager import (
    BUCKET_SIZE,
    NEW_BUCKET_COUNT,
    NEW_BUCKETS_PER_ADDRESS,
    AddressManager,
    ExtendedPeerInfo,
)
from chia.server.address_manager_sql_shared import (
    add_peer,
    clear_peers,
    get_all_peers,
    get_new_table,
    set_new_table,
    update_metadata,
)

Node = tuple[int, ExtendedPeerInfo]
Table = tuple[int, int]

log = logging.getLogger(__name__)


class AddressManagerStore:
    @classmethod
    async def initialise(cls, connection: aiosqlite.Connection) -> None:
        await connection.execute("""
                CREATE TABLE IF NOT EXISTS peers (
                    node_id INTEGER PRIMARY KEY,
                    info TEXT
                )
            """)
        await connection.execute("""
                CREATE TABLE IF NOT EXISTS metadata_table (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
        await connection.execute("CREATE TABLE IF NOT EXISTS peer_new_table(node_id int, bucket int)")
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
        new_table_entries: list[tuple[int, int]] = []
        unique_ids: dict[int, int] = {}
        count_ids = 0
        metadata: list[tuple[str, str]] = []
        trieds: list[tuple[int, str]] = []
        await clear_peers(connection)
        await connection.commit()

        tried_ids = 0
        for node_id, info in address_manager.map_info.items():
            unique_ids[node_id] = count_ids
            if info.ref_count > 0:
                assert count_ids != address_manager.new_count
                await add_peer(count_ids, info.to_string(), connection)
                count_ids += 1
            if info.is_tried:
                tried_ids += 1
                trieds.append((tried_ids, info.to_string()))
        metadata.append(("new_count", str(count_ids)))

        for node_id, info_str in trieds:
            assert tried_ids + count_ids != address_manager.tried_count
            await add_peer(count_ids + node_id, info_str, connection)

        # we don't even use this?
        # metadata.append(("tried_count", str(tried_ids)))
        metadata.append(("key", str(address_manager.key)))

        await update_metadata(connection, metadata)

        # store new_table_entries
        for bucket in range(NEW_BUCKET_COUNT):
            for i in range(BUCKET_SIZE):
                if address_manager.new_matrix[bucket][i] != -1:
                    index = unique_ids[address_manager.new_matrix[bucket][i]]
                    new_table_entries.append((index, bucket))
        await set_new_table(new_table_entries, connection)
        log.debug("Peer data serialized successfully")

    @classmethod
    async def deserialize(cls, connection: aiosqlite.Connection) -> AddressManager:
        log.info("Deserializing peer data from database")
        address_manager = AddressManager(db_connection=connection)
        nodes = await get_all_peers(connection)

        # for node_id, info_str in peers:
        #     info = ExtendedPeerInfo.from_string(info_str)
        #     address_manager.map_info[node_id] = info
        address_manager.db_connection = connection
        async with connection.execute("SELECT key, value FROM metadata_table") as cursor:
            metadata: dict[str, str] = {key: value async for key, value in cursor}

            address_manager.key = int(metadata.get("key", 0))
            address_manager.new_count = int(metadata.get("new_count", 0))
            # address_manager.tried_count = int(metadata.get("tried_count", 0))
            address_manager.tried_count = 0

        new_table_entries = await get_new_table(connection)
        # we serialize all the new_table peers first, and then mark the end with new_count
        new_table_nodes = [(node_id, info) for node_id, info in nodes if node_id < address_manager.new_count]

        # load info for new_table peers
        for n, info in new_table_nodes:
            info = ExtendedPeerInfo.from_string(info)
            address_manager.map_addr[info.peer_info.host] = n
            address_manager.map_info[n] = info
            info.random_pos = len(address_manager.random_pos)
            address_manager.random_pos.append(n)
        address_manager.id_count = len(new_table_nodes)

        # load all peers after new_count as tried_table peers
        tried_table_nodes = [
            (node_id, ExtendedPeerInfo.from_string(info))
            for node_id, info in nodes[address_manager.new_count:]
        ]
        # lost_count = 0
        for node_id, info in tried_table_nodes:
            tried_bucket = info.get_tried_bucket(address_manager.key)
            tried_bucket_pos = info.get_bucket_position(address_manager.key, False, tried_bucket)
            if address_manager.tried_matrix[tried_bucket][tried_bucket_pos] == -1:
                info.random_pos = len(address_manager.random_pos)
                info.is_tried = True
                id_count = address_manager.id_count
                address_manager.random_pos.append(id_count)
                address_manager.map_info[id_count] = info
                address_manager.map_addr[info.peer_info.host] = id_count
                address_manager.tried_matrix[tried_bucket][tried_bucket_pos] = id_count
                address_manager.id_count += 1
                address_manager.tried_count += 1
            # else:
            #    lost_count += 1

        # address_manager.tried_count -= lost_count
        for node_id, bucket in new_table_entries:
            if node_id >= 0 and node_id < address_manager.new_count:
                info = address_manager.map_info[node_id]
                bucket_pos = info.get_bucket_position(address_manager.key, True, bucket)
                if address_manager.new_matrix[bucket][bucket_pos] == -1 and info.ref_count < NEW_BUCKETS_PER_ADDRESS:
                    info.ref_count += 1
                    address_manager.new_matrix[bucket][bucket_pos] = node_id

        for node_id, info in list(address_manager.map_info.items()):
            if not info.is_tried and info.ref_count == 0:
                await address_manager.delete_new_entry_(node_id)
        address_manager.load_used_table_positions()
        return address_manager
