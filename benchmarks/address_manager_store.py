from __future__ import annotations

import asyncio
import io
import random
import tempfile
import time
from datetime import datetime
from ipaddress import IPv4Address
from pathlib import Path

import aiofiles
from chia_rs.sized_ints import uint16, uint64

from chia.server.address_manager import (
    NEW_BUCKETS_PER_ADDRESS,
    AddressManager,
    ExtendedPeerInfo,
)
from chia.types.peer_info import TimestampedPeerInfo
from chia.util.files import write_file_async


def generate_random_ip(rand: random.Random) -> str:
    return str(IPv4Address(rand.getrandbits(32)))


def populate_address_manager(num_new: int = 500000, num_tried: int = 200000) -> AddressManager:
    rand = random.Random()
    rand.seed(1337)
    am = AddressManager()
    current_time = int(datetime.now().timestamp())
    total = num_new + num_tried

    for i in range(total):
        host = generate_random_ip(rand)
        port = rand.randint(1024, 65535)
        timestamp = current_time - rand.randint(0, 100000)

        # Construct TimestampedPeerInfo
        tpi = TimestampedPeerInfo(host=host, port=uint16(port), timestamp=uint64(timestamp))

        # Create the ExtendedPeerInfo
        epi = ExtendedPeerInfo(
            addr=tpi,
            src_peer=None,  # will default to itself inside constructor
        )

        am.tried_count += 1  # why do we even have `assert tried_ids != tried_count`?
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
            epi.last_try = timestamp - rand.randint(0, 1000)
            bucket = epi.get_tried_bucket(am.key)
            pos = epi.get_bucket_position(am.key, False, bucket)
            if am.tried_matrix[bucket][pos] == -1:
                am.tried_matrix[bucket][pos] = node_id
                am.tried_count += 1
        else:
            # make a new_table entry
            ref_count = rand.randint(1, NEW_BUCKETS_PER_ADDRESS)
            epi.ref_count = ref_count
            assigned = False
            for _ in range(ref_count):
                bucket = epi.get_new_bucket(am.key)
                pos = epi.get_bucket_position(am.key, True, bucket)
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

            serialised_bytes = address_manager.serialize_bytes()
            await write_file_async(peers_file_path, serialised_bytes, file_mode=0o644)
            end_serialize = time.perf_counter()
            serialize_duration = end_serialize - start_serialize
            total_serialize_time += serialize_duration
            print(f"Serialize time: {serialize_duration:.6f} seconds")

            # Benchmark deserialize
            async with aiofiles.open(peers_file_path, "rb") as f:
                data = io.BytesIO(await f.read())
            start_deserialize = time.perf_counter()
            _ = AddressManager.deserialize_bytes(data)
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
