from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiosqlite

from chia.server.address_manager import NEW_BUCKETS_PER_ADDRESS, AddressManager, ExtendedPeerInfo

Node = Tuple[int, ExtendedPeerInfo]
Table = Tuple[int, int]


async def create_address_manager_from_db(db_path: Path) -> Optional[AddressManager]:
    """
    Creates an AddressManager using data from the SQLite peer db
    """
    async with aiosqlite.connect(db_path) as connection:
        await connection.execute("pragma journal_mode=wal")
        await connection.execute("pragma synchronous=OFF")

        metadata: Dict[str, str] = await get_metadata(connection)
        address_manager: Optional[AddressManager] = None

        if not await is_empty(metadata):
            nodes: List[Node] = await get_nodes(connection)
            new_table_entries: List[Table] = await get_new_table(connection)
            address_manager = create_address_manager(metadata, nodes, new_table_entries)

        return address_manager


async def get_metadata(connection: aiosqlite.Connection) -> Dict[str, str]:
    cursor = await connection.execute("SELECT key, value from peer_metadata")
    metadata = await cursor.fetchall()
    await cursor.close()
    return {key: value for key, value in metadata}


async def get_nodes(connection: aiosqlite.Connection) -> List[Node]:
    cursor = await connection.execute("SELECT node_id, value from peer_nodes")
    nodes_id = await cursor.fetchall()
    await cursor.close()
    return [(node_id, ExtendedPeerInfo.from_string(info_str)) for node_id, info_str in nodes_id]


async def get_new_table(connection: aiosqlite.Connection) -> List[Table]:
    cursor = await connection.execute("SELECT node_id, bucket from peer_new_table")
    entries = await cursor.fetchall()
    await cursor.close()
    return [(node_id, bucket) for node_id, bucket in entries]


async def is_empty(metadata: Dict[str, str]) -> bool:
    if "key" not in metadata:
        return True
    if int(metadata.get("new_count", 0)) > 0:
        return False
    if int(metadata.get("tried_count", 0)) > 0:
        return False
    return True


def create_address_manager(
    metadata: Dict[str, str], nodes: List[Node], new_table_entries: List[Table]
) -> AddressManager:
    address_manager: AddressManager = AddressManager()

    # ----- NOTICE -----
    # The following code was taken from the original implementation of
    # AddressManagerStore.deserialize(). The code is duplicated/preserved
    # here to support migration from older versions.
    # ------------------
    address_manager.key = int(metadata["key"])
    address_manager.new_count = int(metadata["new_count"])
    # address_manager.tried_count = int(metadata["tried_count"])
    address_manager.tried_count = 0

    new_table_nodes = [(node_id, info) for node_id, info in nodes if node_id < address_manager.new_count]
    for n, info in new_table_nodes:
        address_manager.map_addr[info.peer_info.host] = n
        address_manager.map_info[n] = info
        info.random_pos = len(address_manager.random_pos)
        address_manager.random_pos.append(n)
    address_manager.id_count = len(new_table_nodes)
    tried_table_nodes = [(node_id, info) for node_id, info in nodes if node_id >= address_manager.new_count]
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
            address_manager.delete_new_entry_(node_id)
    address_manager.load_used_table_positions()

    return address_manager
