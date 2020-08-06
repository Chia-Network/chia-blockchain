from src.server.address_manager import (
    AddressManager,
    ExtendedPeerInfo,
    NEW_BUCKET_COUNT,
    BUCKET_SIZE,
    NEW_BUCKETS_PER_ADDRESS,
)

import logging
import aiosqlite

log = logging.getLogger(__name__)


class AddressManagerStore:
    db: aiosqlite.Connection

    @classmethod
    async def create(cls, connection):
        self = cls()
        self.db = connection
        await self.db.commit()

        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS metadata("
            "key text,"
            "value text)"
        )
        await self.db.commit()

        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS nodes("
            "node_id int,"
            "value text)"
        )
        await self.db.commit()

        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS new_table("
            "node_id int,"
            "bucket int)"
        )
        await self.db.commit()
        return self

    async def clear(self):
        cursor = await self.db.execute("DELETE from metadata")
        await cursor.close()
        await self.db.commit()
        cursor = await self.db.execute("DELETE from nodes")
        await cursor.close()
        await self.db.commit()
        cursor = await self.db.execute("DELETE from new_table")
        await cursor.close()
        await self.db.commit()

    async def get_metadata(self):
        cursor = await self.db.execute("SELECT key, value from metadata")
        metadata = await cursor.fetchall()
        await cursor.close()
        return {key: value for key, value in metadata}

    async def is_empty(self):
        metadata = await self.get_metadata()
        if "key" not in metadata:
            return True
        if (
            "new_count" in metadata
            and metadata["new_count"] > 0
        ):
            return False
        if (
            "tried_count" in metadata
            and metadata["tried_count"] > 0
        ):
            return False
        return True

    async def get_nodes(self):
        cursor = await self.db.execute("SELECT node_id, value from nodes")
        nodes_id = await cursor.fetchall()
        await cursor.close()
        return [
            (node_id, ExtendedPeerInfo.from_string(info_str))
            for node_id, info_str in nodes_id
        ]

    async def get_new_table(self):
        cursor = await self.db.execute("SELECT node_id, bucket from new_table")
        entries = await cursor.fetchall()
        await cursor.close()
        return [(node_id, bucket) for node_id, bucket in entries]

    async def set_metadata(self, metadata):
        for key, value in metadata:
            cursor = await self.db.execute(
                "INSERT OR REPLACE INTO metadata VALUES(?, ?)",
                (key, value),
            )
            await cursor.close()
            await self.db.commit()

    async def set_nodes(self, node_list):
        for node_id, peer_info in node_list:
            cursor = await self.db.execute(
                "INSERT OR REPLACE INTO nodes VALUES(?, ?)",
                (node_id, peer_info.to_string())
            )
            await cursor.close()
            await self.db.commit()

    async def set_new_table(self, entries):
        for node_id, bucket in entries:
            cursor = await self.db.execute(
                "INSERT OR REPLACE INTO new_table VALUES(?, ?)",
                (node_id, bucket),
            )
            await cursor.close()
            await self.db.commit()

    async def serialize(self, address_manager: AddressManager):
        metadata = []
        nodes = []
        new_table_entries = []

        metadata.append(("key", str(address_manager.key)))
        metadata.append(("new_count", str(address_manager.new_count)))
        metadata.append(("tried_count", str(address_manager.tried_count)))

        unique_ids = {}
        count_ids = 0

        for node_id, info in address_manager.map_info.items():
            unique_ids[node_id] = count_ids
            if info.ref_count > 0:
                assert count_ids != address_manager.new_count
                nodes.append((count_ids, info))
                count_ids += 1

        tried_ids = 0
        for node_id, info in address_manager.map_info.items():
            if info.is_tried:
                assert info is not None
                assert tried_ids != address_manager.tried_count
                nodes.append((count_ids, info))
                count_ids += 1
                tried_ids += 1

        for bucket in range(NEW_BUCKET_COUNT):
            for i in range(BUCKET_SIZE):
                if address_manager.new_matrix[bucket][i] != -1:
                    index = unique_ids[address_manager.new_matrix[bucket][i]]
                    new_table_entries.append((index, bucket))

        await self.clear()
        await self.set_metadata(metadata)
        await self.set_nodes(nodes)
        await self.set_new_table(new_table_entries)

    async def unserialize(self, address_manager: AddressManager):
        metadata = await self.get_metadata()
        nodes = await self.get_nodes()
        new_table_entries = await self.get_new_table()
        address_manager.clear()

        address_manager.key = int(metadata["key"])
        address_manager.new_count = int(metadata["new_count"])
        address_manager.tried_count = int(metadata["tried_count"])

        new_table_nodes = [
            (node_id, info)
            for node_id, info in nodes
            if node_id < address_manager.new_count
        ]
        for n, info in new_table_nodes:
            address_manager.map_addr[info.peer_info.host] = n
            address_manager.map_info[n] = info
            info.random_pos = len(address_manager.random_pos)
            address_manager.random_pos.append(n)

        tried_table_nodes = [
            (node_id, info)
            for node_id, info in nodes
            if node_id >= address_manager.new_count
        ]
        lost_count = 0
        for node_id, info in tried_table_nodes:
            tried_bucket = info.get_tried_bucket(address_manager.key)
            tried_bucket_pos = info.get_bucket_position(address_manager.key, False, tried_bucket)
            if address_manager.tried_matrix[tried_bucket][tried_bucket_pos] == -1:
                info.random_pos = len(address_manager.random_pos)
                info.is_tried = True
                address_manager.random_pos.append(node_id)
                address_manager.map_info[node_id] = info
                address_manager.map_addr[info.peer_info.host] = node_id
                address_manager.tried_matrix[tried_bucket][tried_bucket_pos] = node_id
            else:
                lost_count += 1

        address_manager.tried_count -= lost_count
        for node_id, bucket in new_table_entries:
            if (node_id >= 0 and node_id < address_manager.new_count):
                info = address_manager.map_info[node_id]
                bucket_pos = info.get_bucket_position(address_manager.key, True, bucket)
                if (
                    address_manager.new_matrix[bucket][bucket_pos] == -1
                    and info.ref_count < NEW_BUCKETS_PER_ADDRESS
                ):
                    info.ref_count += 1
                    address_manager.new_matrix[bucket][bucket_pos] = node_id

        for node_id, info in address_manager.map_info.items():
            if (not info.is_tried and info.ref_count == 0):
                address_manager.delete_new_entry_(node_id)
