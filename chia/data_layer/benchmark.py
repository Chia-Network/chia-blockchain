import asyncio
import sys
import aiosqlite
import time
import os
from random import Random
from chia.util.db_wrapper import DBWrapper
from chia.data_layer.data_store import DataStore
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.path import path_from_root
from chia.data_layer.data_layer_types import Side
from typing import Optional


async def generate_datastore(num_nodes):
    db_path = path_from_root(DEFAULT_ROOT_PATH, "dl_benchmark")
    if os.path.exists(db_path):
        os.remove(db_path)

    connection = await aiosqlite.connect(db_path)
    db_wrapper = DBWrapper(connection)
    data_store = await DataStore.create(db_wrapper=db_wrapper)
    random = Random()
    hint_keys_values = {}

    tree_id = bytes32(b"0" * 32)
    await data_store.create_tree(tree_id)

    insert_time = 0
    insert_count = 0
    autoinsert_time = 0
    autoinsert_count = 0
    delete_time = 0
    delete_count = 0

    for i in range(num_nodes):
        key = i.to_bytes(4, byteorder="big")
        value = (2 * i).to_bytes(4, byteorder="big")
        reference_node_hash: Optional[bytes32] = await data_store.get_terminal_node_for_random_seed(tree_id, random)
        side: Optional[Side] = random.choice([Side.LEFT, Side.RIGHT])

        if i == 0:
            reference_node_hash = None
            side = None
        if i % 3 == 0:
            t1 = time.time()
            await data_store.insert(
                key=key,
                value=value,
                tree_id=tree_id,
                reference_node_hash=reference_node_hash,
                side=side,
                hint_keys_values=hint_keys_values,
            )
            t2 = time.time()
            insert_time += t2 - t1
            insert_count += 1
        elif i % 3 == 1:
            t1 = time.time()
            await data_store.autoinsert(
                key=key,
                value=value,
                tree_id=tree_id,
                hint_keys_values=hint_keys_values,
            )
            t2 = time.time()
            autoinsert_time += t2 - t1
            autoinsert_count += 1
        else:
            t1 = time.time()
            node = await data_store.get_node(reference_node_hash)
            await data_store.delete(key=node.key, tree_id=tree_id, hint_keys_values=hint_keys_values)
            t2 = time.time()
            delete_time += t2 - t1
            delete_count += 1

    print(f"Average insert time: {insert_time / insert_count}")
    print(f"Average autoinsert time: {autoinsert_time / autoinsert_count}")
    print(f"Average delete time: {delete_time / delete_count}")
    print(f"Total time for {num_nodes} operations: {insert_time + autoinsert_time + delete_time}")
    await connection.close()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(generate_datastore(int(sys.argv[1])))
    loop.close()
