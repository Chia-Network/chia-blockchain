from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

from chia_rs.sized_bytes import bytes32

from chia.data_layer.data_layer_util import Side, Status, leaf_hash
from chia.data_layer.data_store import DataStore


async def generate_datastore(num_nodes: int) -> None:
    with tempfile.TemporaryDirectory() as temp_directory:
        temp_directory_path = Path(temp_directory)
        db_path = temp_directory_path.joinpath("dl_benchmark.sqlite")
        print(f"Writing DB to {db_path}")

        if os.path.exists(db_path):
            os.remove(db_path)

        start_time = time.monotonic()
        async with DataStore.managed(
            database=db_path,
            merkle_blobs_path=temp_directory_path.joinpath("merkle-blobs"),
            key_value_blobs_path=temp_directory_path.joinpath("key-value-blobs"),
        ) as data_store:
            store_id = bytes32(b"0" * 32)
            await data_store.create_tree(store_id, status=Status.COMMITTED)

            insert_time = 0.0
            insert_count = 0
            autoinsert_time = 0.0
            autoinsert_count = 0
            delete_time = 0.0
            delete_count = 0

            for i in range(num_nodes):
                key = i.to_bytes(4, byteorder="big")
                value = (2 * i).to_bytes(4, byteorder="big")
                seed = leaf_hash(key, value)
                node = await data_store.get_terminal_node_for_seed(seed, store_id)

                if i % 3 == 0:
                    t1 = time.time()
                    await data_store.autoinsert(
                        key=key,
                        value=value,
                        store_id=store_id,
                        status=Status.COMMITTED,
                    )
                    t2 = time.time()
                    autoinsert_count += 1
                elif i % 3 == 1:
                    assert node is not None
                    reference_node_hash = node.hash
                    side_seed = bytes(seed)[0]
                    side = Side.LEFT if side_seed < 128 else Side.RIGHT
                    t1 = time.time()
                    await data_store.insert(
                        key=key,
                        value=value,
                        store_id=store_id,
                        reference_node_hash=reference_node_hash,
                        side=side,
                        status=Status.COMMITTED,
                    )
                    t2 = time.time()
                    insert_time += t2 - t1
                    insert_count += 1
                else:
                    t1 = time.time()
                    assert node is not None
                    await data_store.delete(key=node.key, store_id=store_id, status=Status.COMMITTED)
                    t2 = time.time()
                    delete_time += t2 - t1
                    delete_count += 1

            print(f"Average insert time: {insert_time / insert_count}")
            print(f"Average autoinsert time: {autoinsert_time / autoinsert_count}")
            print(f"Average delete time: {delete_time / delete_count}")
            print(f"Total time for {num_nodes} operations: {insert_time + delete_time + autoinsert_time}")
            root = await data_store.get_tree_root(store_id=store_id)
            print(f"Root hash: {root.node_hash}")
            finish_time = time.monotonic()
            print(f"Total runtime: {finish_time - start_time}")


if __name__ == "__main__":
    asyncio.run(generate_datastore(int(sys.argv[1])))
