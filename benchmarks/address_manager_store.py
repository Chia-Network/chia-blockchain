from __future__ import annotations

import asyncio
import random
import tempfile
import time
from datetime import datetime
from ipaddress import IPv4Address
from pathlib import Path

from chia_rs.sized_ints import uint16, uint64

from chia.server.address_manager import (
    BUCKET_SIZE,
    NEW_BUCKET_COUNT,
    NEW_BUCKETS_PER_ADDRESS,
    TRIED_BUCKET_COUNT,
    AddressManager,
    ExtendedPeerInfo,
)
from chia.server.address_manager_store import AddressManagerStore
from chia.types.peer_info import TimestampedPeerInfo


def generate_random_ip() -> str:
    return str(IPv4Address(random.getrandbits(32)))


def populate_address_manager(num_new: int = 500, num_tried: int = 200) -> AddressManager:
    am = AddressManager()
    current_time = int(datetime.now().timestamp())
    total = num_new + num_tried

    for i in range(total):
        host = generate_random_ip()
        port = random.randint(1024, 65535)
        timestamp = current_time - random.randint(0, 100000)

        # Construct TimestampedPeerInfo
        tpi = TimestampedPeerInfo(host=host, port=uint16(port), timestamp=uint64(timestamp))

        # Create the ExtendedPeerInfo
        epi = ExtendedPeerInfo(
            addr=tpi,
            src_peer=None,  # will default to itself inside constructor
        )

        node_id = am.id_count
        am.id_count += 1
        epi.random_pos = len(am.random_pos)
        am.map_info[node_id] = epi
        am.map_addr[epi.peer_info.host] = node_id
        am.random_pos.append(node_id)

        if i >= num_new:
            # make a tried_table entry
            epi.is_tried = True
            epi.last_success = timestamp
            epi.last_try = timestamp - random.randint(0, 1000)
            bucket = random.randint(0, TRIED_BUCKET_COUNT - 1)  # we have a real algorithm for this in pracitce
            pos = random.randint(0, BUCKET_SIZE - 1)
            if am.tried_matrix[bucket][pos] == -1:
                am.tried_matrix[bucket][pos] = node_id
                am.tried_count += 1
        else:
            # make a new_table entry
            ref_count = random.randint(1, NEW_BUCKETS_PER_ADDRESS)
            epi.ref_count = ref_count
            assigned = False
            for _ in range(ref_count):
                bucket = random.randint(0, NEW_BUCKET_COUNT - 1)
                pos = random.randint(0, BUCKET_SIZE - 1)
                if am.new_matrix[bucket][pos] == -1:
                    am.new_matrix[bucket][pos] = node_id
                    am.new_count += 1
                    assigned = True
                    break
            if not assigned:
                # fallback if no bucket available
                epi.ref_count = 0

    return am


async def benchmark_serialize_deserialize(iterations: int = 5) -> None:
    """
    Benchmarks the serialization and deserialization of peer data.
    """

    total_serialize_time = 0.0
    total_deserialize_time = 0.0

    with tempfile.TemporaryDirectory() as tmpdir:
        peers_file_path = Path(tmpdir) / "peers.dat"

        for i in range(iterations):
            address_manager: AddressManager = populate_address_manager()
            print(f"--- Benchmark Run {i + 1} ---")

            # Benchmark serialize
            start_serialize = time.perf_counter()
            await AddressManagerStore.serialize(address_manager, peers_file_path)
            end_serialize = time.perf_counter()
            serialize_duration = end_serialize - start_serialize
            total_serialize_time += serialize_duration
            print(f"Serialize time: {serialize_duration:.6f} seconds")

            # Benchmark deserialize
            start_deserialize = time.perf_counter()
            _ = await AddressManagerStore._deserialize(peers_file_path)
            end_deserialize = time.perf_counter()
            deserialize_duration = end_deserialize - start_deserialize
            total_deserialize_time += deserialize_duration
            print(f"Deserialize time: {deserialize_duration:.6f} seconds")

        print(f"\n=== Benchmark Summary ({iterations} iterations) ===")
        print(f"Average serialize time:   {total_serialize_time / iterations:.6f} seconds")
        print(f"Average deserialize time: {total_deserialize_time / iterations:.6f} seconds")


async def main() -> None:
    await benchmark_serialize_deserialize(iterations=10)


if __name__ == "__main__":
    asyncio.run(main())
