from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from chia.data_layer.data_layer_util import Side, TerminalNode, leaf_hash
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32


async def generate_datastore(num_nodes: int, slow_mode: bool) -> None:
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
            autoinsert_time = 0.0
            autoinsert_count = 0
            delete_time = 0.0
            delete_count = 0

            for i in range(num_nodes):
                key = i.to_bytes(4, byteorder="big")
                value = (2 * i).to_bytes(4, byteorder="big")
                seed = leaf_hash(key=key, value=value)
                reference_node_hash: Optional[bytes32] = await data_store.get_terminal_node_for_seed(store_id, seed)
                side: Optional[Side] = data_store.get_side_for_seed(seed)

                if i == 0:
                    reference_node_hash = None
                    side = None
                if i % 3 == 0:
                    t1 = time.time()
                    if not slow_mode:
                        await data_store.insert(
                            key=key,
                            value=value,
                            store_id=store_id,
                            reference_node_hash=reference_node_hash,
                            side=side,
                        )
                    else:
                        await data_store.insert(
                            key=key,
                            value=value,
                            store_id=store_id,
                            reference_node_hash=reference_node_hash,
                            side=side,
                            use_optimized=False,
                        )
                    t2 = time.time()
                    insert_time += t2 - t1
                    insert_count += 1
                elif i % 3 == 1:
                    t1 = time.time()
                    if not slow_mode:
                        await data_store.autoinsert(key=key, value=value, store_id=store_id)
                    else:
                        await data_store.autoinsert(
                            key=key,
                            value=value,
                            store_id=store_id,
                            use_optimized=False,
                        )
                    t2 = time.time()
                    autoinsert_time += t2 - t1
                    autoinsert_count += 1
                else:
                    t1 = time.time()
                    assert reference_node_hash is not None
                    node = await data_store.get_node(reference_node_hash)
                    assert isinstance(node, TerminalNode)
                    if not slow_mode:
                        await data_store.delete(key=node.key, store_id=store_id)
                    else:
                        await data_store.delete(key=node.key, store_id=store_id, use_optimized=False)
                    t2 = time.time()
                    delete_time += t2 - t1
                    delete_count += 1

            print(f"Average insert time: {insert_time / insert_count}")
            print(f"Average autoinsert time: {autoinsert_time / autoinsert_count}")
            print(f"Average delete time: {delete_time / delete_count}")
            print(f"Total time for {num_nodes} operations: {insert_time + autoinsert_time + delete_time}")
            root = await data_store.get_tree_root(store_id=store_id)
            print(f"Root hash: {root.node_hash}")


if __name__ == "__main__":
    slow_mode = False
    if len(sys.argv) > 2 and sys.argv[2] == "slow":
        slow_mode = True
    asyncio.run(generate_datastore(int(sys.argv[1]), slow_mode))
