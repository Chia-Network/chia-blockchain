import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import aiosqlite

from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper


async def download_client_data(delta: bool, foldername: str) -> None:
    with tempfile.TemporaryDirectory() as temp_directory:
        temp_directory_path = Path(temp_directory)
        db_path = temp_directory_path.joinpath("dl_server_util.sqlite")
        connection = await aiosqlite.connect(db_path)
        db_wrapper = DBWrapper(connection)
        data_store = await DataStore.create(db_wrapper=db_wrapper)
        tree_id = bytes32(b"0" * 32)
        await data_store.create_tree(tree_id)
        generation = 0
        tot = 0.0
        with open(foldername + "/roots.dat", "r") as reader:
            while True:
                root_entry = reader.readline()
                if root_entry is None or root_entry == "":
                    break
                if not delta:
                    filename = foldername + f"/{generation}.dat"
                else:
                    filename = foldername + f"/{generation}-delta.dat"
                print(f"Parsing file {filename}.")
                t1 = time.time()
                generation += 1
                t2 = time.time()
                print(f"Inserted root {root_entry.rstrip()}. Total time: {t2 - t1}")
                tot += t2 - t1
        print(f"Total time: {tot}")
        await connection.close()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    delta = False
    if len(sys.argv) > 1 and sys.argv[1] == "delta":
        delta = True
    if len(sys.argv) > 2:
        foldername = sys.argv[2]
    else:
        foldername = os.getcwd() + "/dl_server_files"
    loop.run_until_complete(download_client_data(delta, foldername))
    loop.close()
