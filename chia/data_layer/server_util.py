import sys
import os
import asyncio
import tempfile
import aiosqlite
from random import Random
from pathlib import Path
from chia.util.db_wrapper import DBWrapper
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32


async def generate_server_files(num_batches: int, num_ops_per_batch: int, foldername: str) -> None:
    with tempfile.TemporaryDirectory() as temp_directory:
        if os.path.exists(foldername):
            raise RuntimeError("Path already exists, delete it first.")
        os.mkdir(foldername)

        temp_directory_path = Path(temp_directory)
        db_path = temp_directory_path.joinpath("dl_server_util.sqlite")
        print(f"Writing DB to {db_path}")

        connection = await aiosqlite.connect(db_path)
        db_wrapper = DBWrapper(connection)
        data_store = await DataStore.create(db_wrapper=db_wrapper)
        tree_id = bytes32(b"0" * 32)
        await data_store.create_tree(tree_id)
        random = Random()
        random.seed(100, version=2)

        keys: List[bytes] = []
        counter = 0
        for batch in range(num_batches):
            changelist: List[Dict[str, Any]] = [] 
            for operation in range(num_ops_per_batch):
                if random.randint(0, 4) > 0 or len(keys) == 0:
                    key = counter.to_bytes(4, byteorder="big")
                    value = (2 * counter).to_bytes(4, byteorder="big")
                    keys.append(key)
                    changelist.append({"action": "insert", "key": key, "value": value})
                else:
                    key = random.choice(keys)
                    keys.remove(key)
                    changelist.append({"action": "delete", "key": key})
                counter += 1
            print(f"Inserting batch {batch}.")
            await data_store.insert_batch(tree_id, changelist)
            print(f"Inserted batch {batch}.")
            filename_full_tree = foldername + f"/{batch}.dat"
            filename_diff_tree = foldername + f"/{batch}-delta.dat"
            root = await data_store.get_tree_root(tree_id)
            print(f"Batch: {batch}. Root hash: {root.node_hash}")
            print(f"Full tree: {filename_full_tree}. Diff tree: {filename_diff_tree}.")
            await data_store.write_tree_to_file(root, root.node_hash, tree_id, False, filename_full_tree)
            await data_store.write_tree_to_file(root, root.node_hash, tree_id, True, filename_diff_tree)

        await connection.close()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    num_batches = int(sys.argv[1])
    num_ops_per_batch = int(sys.argv[2])
    if len(sys.argv) > 3:
        foldername = sys.argv[3]
    else:
        foldername = os.getcwd() + "/dl_server_files"
    loop.run_until_complete(generate_server_files(num_batches, num_ops_per_batch, foldername))
    loop.close()
