from __future__ import annotations

import asyncio
import os
import random
import sys
import tempfile
import time
from pathlib import Path

from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32


async def generate_datastore(num_nodes: int) -> None:
    with tempfile.TemporaryDirectory() as temp_directory:
        temp_directory_path = Path(temp_directory)
        db_path = temp_directory_path.joinpath("dl_benchmark.sqlite")
        print(f"Writing DB to {db_path}")

        if os.path.exists(db_path):
            os.remove(db_path)

        async with DataStore.managed(database=db_path) as data_store:
            store_id = bytes32(b"0" * 32)
            await data_store.create_tree(store_id)

            insert_time = 0.0
            insert_count = 0
            delete_time = 0.0
            delete_count = 0
            keys: list[bytes] = []

            for i in range(num_nodes):
                key = i.to_bytes(4, byteorder="big")
                value = (2 * i).to_bytes(4, byteorder="big")
                keys.append(key)

                if i % 3 == 0 or i % 3 == 1:
                    t1 = time.time()
                    await data_store.insert(
                        key=key,
                        value=value,
                        store_id=store_id,
                    )
                    t2 = time.time()
                    insert_time += t2 - t1
                    insert_count += 1
                else:
                    key = random.choice(keys)
                    keys.remove(key)
                    t1 = time.time()
                    await data_store.delete(key=key, store_id=store_id)
                    t2 = time.time()
                    delete_time += t2 - t1
                    delete_count += 1

            print(f"Average insert time: {insert_time / insert_count}")
            print(f"Average delete time: {delete_time / delete_count}")
            print(f"Total time for {num_nodes} operations: {insert_time + delete_time}")
            root = await data_store.get_tree_root(store_id=store_id)
            print(f"Root hash: {root.node_hash}")


if __name__ == "__main__":
    asyncio.run(generate_datastore(int(sys.argv[1])))
