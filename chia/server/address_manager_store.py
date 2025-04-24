from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from timeit import default_timer as timer
from typing import Optional

import aiofiles
from chia_rs.sized_ints import uint32, uint64

from chia.server.address_manager import (
    BUCKET_SIZE,
    NEW_BUCKET_COUNT,
    NEW_BUCKETS_PER_ADDRESS,
    AddressManager,
    ExtendedPeerInfo,
)
from chia.util.files import write_file_async
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class PeerDataSerialization(Streamable):
    """
    Serializable property bag for the peer data that was previously stored in sqlite.
    """

    metadata: list[tuple[str, str]]
    nodes: list[tuple[uint64, str]]
    new_table: list[tuple[uint64, uint64]]


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

    @classmethod
    async def create_address_manager(cls, peers_file_path: Path) -> AddressManager:
        """
        Create an address manager using data deserialized from a peers file.
        """
        address_manager: Optional[AddressManager] = None
        if peers_file_path.exists():
            try:
                log.info(f"Loading peers from {peers_file_path}")
                # try using the old method
                address_manager = await cls._deserialize(peers_file_path)
            except Exception:
                try:
                    # try using the new method
                    data: Optional[bytes] = None
                    async with aiofiles.open(peers_file_path, "rb") as f:
                        data = await f.read()
                    assert data is not None
                    address_manager = await cls.deserialize_bytes(data)
                except Exception:
                    log.exception(f"Unable to create address_manager from {peers_file_path}")

        if address_manager is None:
            log.info("Creating new address_manager")
            address_manager = AddressManager()

        return address_manager

    @classmethod
    async def serialize_bytes(cls, address_manager: AddressManager, peers_file_path: Path) -> None:
        out = bytearray()
        nodes = bytearray()
        trieds = bytearray()
        new_table = bytearray()
        unique_ids: dict[int, int] = {}
        count_ids: int = 0

        for node_id, info in address_manager.map_info.items():
            unique_ids[node_id] = count_ids
            if info.ref_count > 0:
                assert count_ids != address_manager.new_count
                info.append_bytes(nodes)
                count_ids += 1
            if info.is_tried:
                info.append_bytes(nodes)

        out.extend(address_manager.key.to_bytes(32, byteorder="big"))
        out.extend(uint64(count_ids).stream_to_bytes())

        count = 0
        for bucket in range(NEW_BUCKET_COUNT):
            for i in range(BUCKET_SIZE):
                if address_manager.new_matrix[bucket][i] != -1:
                    count += 1
                    new_table.extend(uint64(unique_ids[address_manager.new_matrix[bucket][i]]).stream_to_bytes())
                    new_table.extend(uint64(bucket).stream_to_bytes())

        # give ourselves a clue how long the new_table is
        out.extend(uint32(count).stream_to_bytes())
        out.extend(new_table)

        out.extend(nodes)
        out.extend(trieds)
        await write_file_async(peers_file_path, bytes(out), file_mode=0o644)

    @classmethod
    async def deserialize_bytes(cls, data: bytes) -> AddressManager:
        address_manager = AddressManager()
        offset = 0

        def decode_uint64(offset: int, data: bytes) -> tuple[uint64, int]:
            value = uint64.from_bytes(data[offset : offset + 8])
            return value, offset + 8

        def decode_uint32(offset: int, data: bytes) -> tuple[uint32, int]:
            value = uint32.from_bytes(data[offset : offset + 4])
            return value, offset + 4

        address_manager.key = int.from_bytes(data[offset : offset + 32], byteorder="big")
        offset += 32
        address_manager.new_count, offset = decode_uint64(offset, data)

        # deserialize new_table
        new_table_count, offset = decode_uint32(offset, data)
        new_table_nodes: list[tuple[uint64, uint64]] = []
        for i in range(0, new_table_count):
            node_id = uint64(uint64.from_bytes(data[offset : offset + 8]))
            offset += 8
            bucket = uint64(uint64.from_bytes(data[offset : offset + 8]))
            offset += 8
            new_table_nodes.append((node_id, bucket))

        # deserialize node info
        address_manager.id_count = 0
        while offset < len(data):
            info, offset = ExtendedPeerInfo.from_bytes(data, offset)
            # check if we're a new node
            if address_manager.id_count < address_manager.new_count:
                address_manager.map_addr[info.peer_info.host] = address_manager.id_count
                address_manager.map_info[address_manager.id_count] = info
                info.random_pos = len(address_manager.random_pos)
                address_manager.random_pos.append(address_manager.id_count)
                address_manager.id_count += 1
            else:
                # we're a tried node
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

        # process
        for node_id, bucket in new_table_nodes:
            if node_id >= 0 and node_id < address_manager.new_count:
                info = address_manager.map_info[node_id]
                bucket_pos = info.get_bucket_position(address_manager.key, True, bucket)
                if address_manager.new_matrix[bucket][bucket_pos] == -1 and info.ref_count < NEW_BUCKETS_PER_ADDRESS:
                    info.ref_count += 1
                    address_manager.new_matrix[bucket][bucket_pos] = node_id

        # remove deads
        for id, info in list(address_manager.map_info.items()):
            if not info.is_tried and info.ref_count == 0:
                address_manager.delete_new_entry_(id)

        address_manager.load_used_table_positions()

        return address_manager

    # This function is deprecated in favour of deserialize_bytes()
    # it remains here for backwards compatibility and migration
    @classmethod
    async def _deserialize(cls, peers_file_path: Path) -> AddressManager:
        """
        Create an address manager using data deserialized from a peers file.
        """
        peer_data: Optional[PeerDataSerialization] = None
        address_manager = AddressManager()
        start_time = timer()
        # if this fails, we pass the exception up to the function that called us and try the other type of deserializing
        peer_data = await cls._read_peers(peers_file_path)

        if peer_data is not None:
            metadata: dict[str, str] = {key: value for key, value in peer_data.metadata}
            nodes: list[tuple[int, ExtendedPeerInfo]] = [
                (node_id, ExtendedPeerInfo.from_string(info_str)) for node_id, info_str in peer_data.nodes
            ]
            new_table_entries: list[tuple[int, int]] = [(node_id, bucket) for node_id, bucket in peer_data.new_table]
            log.debug(f"Deserializing peer data took {timer() - start_time} seconds")

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
                    if (
                        address_manager.new_matrix[bucket][bucket_pos] == -1
                        and info.ref_count < NEW_BUCKETS_PER_ADDRESS
                    ):
                        info.ref_count += 1
                        address_manager.new_matrix[bucket][bucket_pos] = node_id

            for node_id, info in list(address_manager.map_info.items()):
                if not info.is_tried and info.ref_count == 0:
                    address_manager.delete_new_entry_(node_id)

            address_manager.load_used_table_positions()

        return address_manager

    # this is a deprecated function, only kept around for migration to the new format
    @classmethod
    async def _read_peers(cls, peers_file_path: Path) -> PeerDataSerialization:
        """
        Read the peers file and return the data as a PeerDataSerialization object.
        """
        async with aiofiles.open(peers_file_path, "rb") as f:
            return PeerDataSerialization.from_bytes(await f.read())
