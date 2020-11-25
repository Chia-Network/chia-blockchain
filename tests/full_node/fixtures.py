import pickle
import aiosqlite
import pytest
from typing import List
from pathlib import Path
from src.full_node.block_store import BlockStore
from src.consensus.blockchain import Blockchain
from src.full_node.coin_store import CoinStore
from src.types.full_block import FullBlock
from tests.setup_nodes import test_constants, bt
from os import path


@pytest.fixture(scope="function")
async def empty_blockchain():
    """
    Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
    """
    db_path = Path("blockchain_test.db")
    if db_path.exists():
        db_path.unlink()
    connection = await aiosqlite.connect(db_path)
    coin_store = await CoinStore.create(connection)
    store = await BlockStore.create(connection)
    bc1 = await Blockchain.create(coin_store, store, test_constants)
    assert bc1.get_peak() is None

    yield bc1

    await connection.close()
    bc1.shut_down()


@pytest.fixture(scope="module")
async def default_400_blocks():
    yield persistent_blocks(400, "test_blocks_400.db")


@pytest.fixture(scope="module")
async def default_1000_blocks():
    yield persistent_blocks(1000, "test_blocks_1000.db")


def persistent_blocks(num_of_blocks, db_name):
    # try loading from disc, if not create new blocks.db file
    if path.exists(db_name):
        try:
            file = open(db_name, "rb")
            block_bytes_list: List[bytes] = pickle.load(file)
            blocks: List[FullBlock] = []
            for block_bytes in block_bytes_list:
                blocks.append(FullBlock.from_bytes(block_bytes))
            file.close()
            if len(blocks) == num_of_blocks:
                print(f"\n loaded {db_name} with {len(blocks)} blocks")
                return blocks
        except EOFError:
            print("\n error reading db file")

    return new_test_db(db_name, num_of_blocks)


def new_test_db(db_name, num_of_blocks):
    print(f"create {db_name} with {num_of_blocks} blocks")
    file = open(db_name, "wb+")
    blocks: List[FullBlock] = bt.get_consecutive_blocks(num_of_blocks)
    block_bytes_list: List[bytes] = []
    for block in blocks:
        block_bytes_list.append(bytes(block))
    pickle.dump(block_bytes_list, file)
    file.close()
    return blocks
