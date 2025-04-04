from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from timeit import default_timer as timer
from typing import Any, Optional

import aiofiles
from chia_rs.sized_ints import uint16, uint64

from chia.server.address_manager import (
    BUCKET_SIZE,
    NEW_BUCKET_COUNT,
    NEW_BUCKETS_PER_ADDRESS,
    AddressManager,
    ExtendedPeerInfo,
)
from chia.types.peer_info import PeerInfo, TimestampedPeerInfo
from chia.util.files import write_file_async
from chia.util.ip_address import IPAddress
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class PeerDataSerialization(Streamable):
    """
    Serializable property bag for the peer data that was previously stored in sqlite.
    """

    metadata: list[tuple[str, str]]
    nodes: list[tuple[uint64, bytes]]
    new_table: list[tuple[uint64, uint64]]


@streamable
@dataclass(frozen=True)
class ExtendedPeerInfoSerialization(Streamable):
    peer_info_host: bytes
    peer_info_port: uint16
    timestamp: uint64
    src_host: bytes
    src_port: uint16

    @classmethod
    def from_extended_peer_info(cls, epi: ExtendedPeerInfo) -> ExtendedPeerInfoSerialization:
        assert epi.src is not None
        peer_ip_bytes = IPAddress.create(epi.peer_info.host)._inner.packed
        src_ip_bytes = IPAddress.create(epi.src.host)._inner.packed
        return ExtendedPeerInfoSerialization(
            peer_ip_bytes, epi.peer_info.port, uint64(epi.timestamp), src_ip_bytes, epi.src.port
        )

    @classmethod
    def to_extended_peer_info(cls, bytes: bytes) -> ExtendedPeerInfo:
        epi = ExtendedPeerInfoSerialization.from_bytes(bytes)

        peer_ip = IPAddress(ip_address(epi.peer_info_host))
        src_ip = IPAddress(ip_address(epi.src_host))

        peer_info = PeerInfo(peer_ip, epi.peer_info_port)
        src_peer_info = PeerInfo(src_ip, epi.src_port)
        return ExtendedPeerInfo(TimestampedPeerInfo(str(peer_info.host), peer_info.port, epi.timestamp), src_peer_info)


async def makePeerDataSerialization(
    metadata: list[tuple[str, Any]], nodes: list[tuple[uint64, bytes]], new_table: list[tuple[int, int]]
) -> bytes:
    """
    Create a PeerDataSerialization, adapting the provided collections
    """
    transformed_new_table: list[tuple[uint64, uint64]] = []

    for index, [node_id, bucket_id] in enumerate(new_table):
        transformed_new_table.append((uint64(node_id), uint64(bucket_id)))
        # Come up to breathe for a moment
        if index % 1000 == 0:
            await asyncio.sleep(0)

    serialized_bytes: bytes = bytes(PeerDataSerialization(metadata, nodes, transformed_new_table))
    return serialized_bytes


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
                address_manager = await cls._deserialize(peers_file_path)
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
        nodes: list[tuple[uint64, bytes]] = []
        new_table_entries: list[tuple[int, int]] = []
        unique_ids: dict[int, int] = {}
        count_ids: int = 0
        trieds: list[tuple[int, ExtendedPeerInfo]] = []
        log.info("Serializing peer data")
        metadata.append(("key", str(address_manager.key)))

        tried_ids = 0
        for node_id, info in address_manager.map_info.items():
            unique_ids[node_id] = count_ids
            if info.ref_count > 0:
                assert count_ids != address_manager.new_count
                nodes.append((uint64(count_ids), bytes(ExtendedPeerInfoSerialization.from_extended_peer_info(info))))
                count_ids += 1
            if info.is_tried:
                assert tried_ids != address_manager.tried_count
                trieds.append((count_ids, info))
                tried_ids += 1
        metadata.append(("new_count", str(count_ids)))

        for node_id, info in trieds:
            assert tried_ids + count_ids != address_manager.tried_count
            nodes.append((uint64(count_ids + node_id), bytes(ExtendedPeerInfoSerialization.from_extended_peer_info(info))))

        for bucket in range(NEW_BUCKET_COUNT):
            for i in range(BUCKET_SIZE):
                if address_manager.new_matrix[bucket][i] != -1:
                    index = unique_ids[address_manager.new_matrix[bucket][i]]
                    new_table_entries.append((index, bucket))

        try:
            # Ensure the parent directory exists
            peers_file_path.parent.mkdir(parents=True, exist_ok=True)
            start_time = timer()
            await cls._write_peers(peers_file_path, metadata, nodes, new_table_entries)
            log.debug(f"Serializing peer data took {timer() - start_time} seconds")
        except Exception:
            log.exception(f"Failed to write peer data to {peers_file_path}")

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
            nodes: list[tuple[int, ExtendedPeerInfo]] = [
                (node_id, ExtendedPeerInfoSerialization.to_extended_peer_info(info_bytes))
                for node_id, info_bytes in peer_data.nodes
            ]
            new_table_entries: list[tuple[int, int]] = [(node_id, bucket) for node_id, bucket in peer_data.new_table]
            log.debug(f"Deserializing peer data took {timer() - start_time} seconds")

            address_manager.key = int(metadata["key"])
            address_manager.new_count = int(metadata["new_count"])
            # address_manager.tried_count = int(metadata["tried_count"])
            address_manager.tried_count = 0

            for n, info in nodes[: address_manager.new_count]:
                address_manager.map_addr[info.peer_info.host] = n
                address_manager.map_info[n] = info
                info.random_pos = len(address_manager.random_pos)
                address_manager.random_pos.append(n)
            address_manager.id_count = address_manager.new_count
            # lost_count = 0
            for node_id, info in nodes[address_manager.new_count :]:
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
        nodes: list[tuple[int, ExtendedPeerInfo]],
        new_table: list[tuple[int, int]],
    ) -> None:
        """
        Serializes the given peer data and writes it to the peers file.
        """
        serialized_bytes: bytes = await makePeerDataSerialization(metadata, nodes, new_table)
        await write_file_async(peers_file_path, serialized_bytes, file_mode=0o644)
