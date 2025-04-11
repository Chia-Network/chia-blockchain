from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from timeit import default_timer as timer
from typing import Any, Optional

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
    nodes: list[bytes]
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
                address_manager = await cls.deserialize_bytes(peers_file_path)
            except Exception:
                log.exception(f"Unable to create address_manager from {peers_file_path}")

        if address_manager is None:
            log.info("Creating new address_manager")
            address_manager = AddressManager()

        return address_manager

    @classmethod
    async def serialize(cls, address_manager: AddressManager, peers_file_path: Path) -> None:
        """
        Serialize the address manager's peer data to a file.
        """
        metadata: list[tuple[str, str]] = []
        nodes: bytearray = bytearray()
        new_table_entries: list[tuple[uint64, uint64]] = []
        unique_ids: dict[int, int] = {}
        count_ids: int = 0
        trieds: bytearray = bytearray()
        log.info("Serializing peer data")
        metadata.append(("key", str(address_manager.key)))

        for node_id, info in address_manager.map_info.items():
            unique_ids[node_id] = count_ids
            if info.ref_count > 0:
                assert count_ids != address_manager.new_count
                nodes.append(info.to_bytes())
                count_ids += 1
            if info.is_tried:
                trieds.append(info.to_bytes())
        metadata.append(("new_count", str(count_ids)))

        nodes.extend(trieds)

        for bucket in range(NEW_BUCKET_COUNT):
            for i in range(BUCKET_SIZE):
                if address_manager.new_matrix[bucket][i] != -1:
                    new_table_entries.append(
                        (uint64(unique_ids[address_manager.new_matrix[bucket][i]]), uint64(bucket))
                    )

        try:
            # Ensure the parent directory exists
            peers_file_path.parent.mkdir(parents=True, exist_ok=True)
            start_time = timer()
            await cls._write_peers(peers_file_path, metadata, nodes, new_table_entries)
            log.debug(f"Serializing peer data took {timer() - start_time} seconds")
        except Exception:
            log.exception(f"Failed to write peer data to {peers_file_path}")

    @classmethod
    async def serialize_bytes(cls, address_manager: AddressManager, peers_file_path: Path) -> None:
        out = bytearray()
        nodes = bytearray()
        trieds = bytearray()
        new_table = bytearray()
        unique_ids: dict[int, int] = {}
        count_ids: uint64 = 0

        for node_id, info in address_manager.map_info.items():
            unique_ids[node_id] = count_ids
            if info.ref_count > 0:
                assert count_ids != address_manager.new_count
                nodes.extend(info.to_bytes())
                count_ids += 1
            if info.is_tried:
                trieds.extend(info.to_bytes())

        out.extend(address_manager.key.to_bytes(32, byteorder="big"))
        out.extend(uint64(count_ids).stream_to_bytes())

        # serialize new_table - this will break if we change bucket sizes, but thats ok
        # for id_val, bucket in address_manager.new_matrix:
        #     out.extend(uint64(id_val).stream_to_bytes())
        #     out.extend(uint64(bucket).stream_to_bytes())
        count = 0
        for bucket in range(NEW_BUCKET_COUNT):
            for i in range(BUCKET_SIZE):
                if address_manager.new_matrix[bucket][i] != -1:
                    count += 1  # TODO: check if this is the same as count_ids - we can remove new_table bytearray if so
                    new_table.extend(uint64(unique_ids[address_manager.new_matrix[bucket][i]]).stream_to_bytes())
                    new_table.extend(uint64(bucket).stream_to_bytes())

        # give ourselves a clue how long the new_table is
        out.extend(uint32(count).stream_to_bytes())
        out.extend(new_table)

        out.extend(nodes)
        out.extend(trieds)
        await write_file_async(peers_file_path, bytes(out), file_mode=0o644)

    @classmethod
    async def deserialize_bytes(cls, peers_file_path: Path) -> None:
        data: Optional[bytes] = None
        address_manager = AddressManager()
        offset = 0
        async with aiofiles.open(peers_file_path, "rb") as f:
            data = await f.read()
        assert data is not None

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
        for node_id, info in list(address_manager.map_info.items()):
            if not info.is_tried and info.ref_count == 0:
                address_manager.delete_new_entry_(node_id)

        address_manager.load_used_table_positions()

        return address_manager

    @classmethod
    async def _deserialize(cls, peers_file_path: Path) -> AddressManager:
        """
        Create an address manager using data deserialized from a peers file.
        """
        peer_data: Optional[PeerDataSerialization] = None
        address_manager = AddressManager()
        start_time = timer()
        try:
            peer_data = await cls._read_peers(peers_file_path)
        except Exception:
            log.exception(f"Unable to deserialize peers from {peers_file_path}")

        if peer_data is not None:
            metadata: dict[str, str] = {key: value for key, value in peer_data.metadata}

            new_table_entries: list[tuple[int, int]] = [(node_id, bucket) for node_id, bucket in peer_data.new_table]
            log.debug(f"Deserializing peer data took {timer() - start_time} seconds")

            address_manager.key = int(metadata["key"])
            address_manager.new_count = int(metadata["new_count"])
            # address_manager.tried_count = int(metadata["tried_count"])
            address_manager.tried_count = 0

            n = 0
            for info_bytes in peer_data.nodes[: address_manager.new_count]:
                info = ExtendedPeerInfo.from_bytes(info_bytes)
                address_manager.map_addr[info.peer_info.host] = n
                address_manager.map_info[n] = info
                info.random_pos = len(address_manager.random_pos)
                address_manager.random_pos.append(n)
                n += 1
            address_manager.id_count = address_manager.new_count
            for info_bytes in peer_data.nodes[address_manager.new_count :]:
                info = ExtendedPeerInfo.from_bytes(info_bytes)

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

    @classmethod
    async def _read_peers(cls, peers_file_path: Path) -> PeerDataSerialization:
        """
        Read the peers file and return the data as a PeerDataSerialization object.
        """
        async with aiofiles.open(peers_file_path, "rb") as f:
            return PeerDataSerialization.from_bytes(await f.read())

    @classmethod
    async def _write_peers(
        cls,
        peers_file_path: Path,
        metadata: list[tuple[str, Any]],
        nodes: list[bytes],
        new_table: list[tuple[uint64, uint64]],
    ) -> None:
        """
        Serializes the given peer data and writes it to the peers file.
        """
        serialized_bytes: bytes = bytes(PeerDataSerialization(metadata, nodes, new_table))
        await write_file_async(peers_file_path, serialized_bytes, file_mode=0o644)
