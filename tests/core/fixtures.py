import pickle
import aiosqlite
import pytest
from typing import List
from pathlib import Path
from src.full_node.block_store import BlockStore
from src.consensus.blockchain import Blockchain
from src.full_node.coin_store import CoinStore
from src.types.full_block import FullBlock
from src.util.path import mkdir
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
    db_path.unlink()


block_format_version = "b28_1"


@pytest.fixture(scope="session")
async def default_400_blocks():
    return persistent_blocks(400, f"test_blocks_400_{block_format_version}.db", seed=b"alternate2")


@pytest.fixture(scope="session")
async def default_1000_blocks():
    return persistent_blocks(1000, f"test_blocks_1000_{block_format_version}.db")


@pytest.fixture(scope="session")
async def default_10000_blocks():
    return persistent_blocks(10000, f"test_blocks_10000_{block_format_version}.db")


@pytest.fixture(scope="session")
async def default_20000_blocks():
    return persistent_blocks(20000, f"test_blocks_20000_{block_format_version}.db")


def persistent_blocks(num_of_blocks: int, db_name: str, seed: bytes = b""):
    # try loading from disc, if not create new blocks.db file
    # TODO hash fixtures.py and blocktool.py, add to path, delete if the files changed
    block_path_dir = Path("~/.chia/blocks").expanduser()
    file_path = Path(f"~/.chia/blocks/{db_name}").expanduser()
    if not path.exists(block_path_dir):
        mkdir(block_path_dir.parent)
        mkdir(block_path_dir)

    if file_path.exists():
        try:
            bytes_list = file_path.read_bytes()
            block_bytes_list: List[bytes] = pickle.loads(bytes_list)
            blocks: List[FullBlock] = []
            for block_bytes in block_bytes_list:
                blocks.append(FullBlock.from_bytes(block_bytes))
            if len(blocks) == num_of_blocks:
                print(f"\n loaded {file_path} with {len(blocks)} blocks")
                return blocks
        except EOFError:
            print("\n error reading db file")

    return new_test_db(file_path, num_of_blocks, seed)


def new_test_db(path: Path, num_of_blocks: int, seed: bytes):
    print(f"create {path} with {num_of_blocks} blocks")
    blocks: List[FullBlock] = bt.get_consecutive_blocks(num_of_blocks, seed=seed)
    block_bytes_list: List[bytes] = []
    for block in blocks:
        block_bytes_list.append(bytes(block))
    bytes_fn = pickle.dumps(block_bytes_list)
    path.write_bytes(bytes_fn)
    return blocks
