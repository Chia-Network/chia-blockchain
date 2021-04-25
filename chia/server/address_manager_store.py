import logging
from typing import Dict, List, Tuple

import aiosqlite

from chia.server.address_manager import (
    BUCKET_SIZE,
    NEW_BUCKET_COUNT,
    NEW_BUCKETS_PER_ADDRESS,
    AddressManager,
    ExtendedPeerInfo,
)

log = logging.getLogger(__name__)


class AddressManagerStore:
    """
    Metadata table:
    - private key
    - new table count
    - tried table count
    Nodes table:
    * Maps entries from new/tried table to unique node ids.
    - node_id
    - IP, port, together with the IP, port of the source peer.
    New table:
    * Stores node_id, bucket for each occurrence in the new table of an entry.
    * Once we know the buckets, we can also deduce the bucket positions.
    Every other information, such as tried_matrix, map_addr, map_info, random_pos,
    be deduced and it is not explicitly stored, instead it is recalculated.
    """

    db: aiosqlite.Connection

    @classmethod
    async def create(cls, connection) -> "AddressManagerStore":
        self = cls()
        self.db = connection
        await self.db.commit()
        await self.db.execute("pragma journal_mode=wal")
        await self.db.execute("pragma synchronous=2")
        await self.db.execute("CREATE TABLE IF NOT EXISTS peer_metadata(key text,value text)")
        await self.db.commit()

        await self.db.execute("CREATE TABLE IF NOT EXISTS peer_nodes(node_id int,value text)")
        await self.db.commit()

        await self.db.execute("CREATE TABLE IF NOT EXISTS peer_new_table(node_id int,bucket int)")
        await self.db.commit()
        return self

    async def clear(self) -> None:
        cursor = await self.db.execute("DELETE from peer_metadata")
        await cursor.close()
        cursor = await self.db.execute("DELETE from peer_nodes")
        await cursor.close()
        cursor = await self.db.execute("DELETE from peer_new_table")
        await cursor.close()
        await self.db.commit()

    async def get_metadata(self) -> Dict[str, str]:
        cursor = await self.db.execute("SELECT key, value from peer_metadata")
        metadata = await cursor.fetchall()
        await cursor.close()
        return {key: value for key, value in metadata}

    async def is_empty(self) -> bool:
        metadata = await self.get_metadata()
        if "key" not in metadata:
            return True
        if int(metadata.get("new_count", 0)) > 0:
            return False
        if int(metadata.get("tried_count", 0)) > 0:
            return False
        return True

    async def get_nodes(self) -> List[Tuple[int, ExtendedPeerInfo]]:
        cursor = await self.db.execute("SELECT node_id, value from peer_nodes")
        nodes_id = await cursor.fetchall()
        await cursor.close()
        return [(node_id, ExtendedPeerInfo.from_string(info_str)) for node_id, info_str in nodes_id]

    async def get_new_table(self) -> List[Tuple[int, int]]:
        cursor = await self.db.execute("SELECT node_id, bucket from peer_new_table")
        entries = await cursor.fetchall()
        await cursor.close()
        return [(node_id, bucket) for node_id, bucket in entries]

    async def set_metadata(self, metadata) -> None:
        for key, value in metadata:
            cursor = await self.db.execute(
                "INSERT OR REPLACE INTO peer_metadata VALUES(?, ?)",
                (key, value),
            )
            await cursor.close()
        await self.db.commit()

    async def set_nodes(self, node_list) -> None:
        for node_id, peer_info in node_list:
            cursor = await self.db.execute(
                "INSERT OR REPLACE INTO peer_nodes VALUES(?, ?)",
                (node_id, peer_info.to_string()),
            )
            await cursor.close()
        await self.db.commit()

    async def set_new_table(self, entries) -> None:
        for node_id, bucket in entries:
            cursor = await self.db.execute(
                "INSERT OR REPLACE INTO peer_new_table VALUES(?, ?)",
                (node_id, bucket),
            )
            await cursor.close()
        await self.db.commit()

    async def serialize(self, address_manager: AddressManager):
        metadata = []
        nodes = []
        new_table_entries = []
        metadata.append(("key", str(address_manager.key)))

        unique_ids = {}
        count_ids = 0

        for node_id, info in address_manager.map_info.items():
            unique_ids[node_id] = count_ids
            if info.ref_count > 0:
                assert count_ids != address_manager.new_count
                nodes.append((count_ids, info))
                count_ids += 1
        metadata.append(("new_count", str(count_ids)))

        tried_ids = 0
        for node_id, info in address_manager.map_info.items():
            if info.is_tried:
                assert info is not None
                assert tried_ids != address_manager.tried_count
                nodes.append((count_ids, info))
                count_ids += 1
                tried_ids += 1
        metadata.append(("tried_count", str(tried_ids)))

        for bucket in range(NEW_BUCKET_COUNT):
            for i in range(BUCKET_SIZE):
                if address_manager.new_matrix[bucket][i] != -1:
                    index = unique_ids[address_manager.new_matrix[bucket][i]]
                    new_table_entries.append((index, bucket))

        await self.clear()
        await self.set_metadata(metadata)
        await self.set_nodes(nodes)
        await self.set_new_table(new_table_entries)

    async def deserialize(self) -> AddressManager:
        address_manager = AddressManager()
        metadata = await self.get_metadata()
        nodes = await self.get_nodes()
        new_table_entries = await self.get_new_table()
        address_manager.clear()

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
