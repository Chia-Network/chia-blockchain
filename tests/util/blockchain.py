import pickle
from os import path
from pathlib import Path
from typing import List

import aiosqlite

from chia.consensus.blockchain import Blockchain
from chia.consensus.constants import ConsensusConstants
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.types.full_block import FullBlock
from chia.util.db_wrapper import DBWrapper
from chia.util.path import mkdir

from tests.setup_nodes import bt

blockchain_db_counter: int = 0


async def create_blockchain(constants: ConsensusConstants, db_version: int):
    global blockchain_db_counter
    db_path = Path(f"blockchain_test-{blockchain_db_counter}.db")
    if db_path.exists():
        db_path.unlink()
    blockchain_db_counter += 1
    connection = await aiosqlite.connect(db_path)
    wrapper = DBWrapper(connection, db_version)
    coin_store = await CoinStore.create(wrapper)
    store = await BlockStore.create(wrapper)
    hint_store = await HintStore.create(wrapper)
    bc1 = await Blockchain.create(coin_store, store, constants, hint_store, Path("."), 2)
    assert bc1.get_peak() is None
    return bc1, connection, db_path


def persistent_blocks(
    num_of_blocks: int,
    db_name: str,
    seed: bytes = b"",
    empty_sub_slots=0,
    normalized_to_identity_cc_eos: bool = False,
    normalized_to_identity_icc_eos: bool = False,
    normalized_to_identity_cc_sp: bool = False,
    normalized_to_identity_cc_ip: bool = False,
):
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

    return new_test_db(
        file_path,
        num_of_blocks,
        seed,
        empty_sub_slots,
        normalized_to_identity_cc_eos,
        normalized_to_identity_icc_eos,
        normalized_to_identity_cc_sp,
        normalized_to_identity_cc_ip,
    )


def new_test_db(
    path: Path,
    num_of_blocks: int,
    seed: bytes,
    empty_sub_slots: int,
    normalized_to_identity_cc_eos: bool = False,  # CC_EOS,
    normalized_to_identity_icc_eos: bool = False,  # ICC_EOS
    normalized_to_identity_cc_sp: bool = False,  # CC_SP,
    normalized_to_identity_cc_ip: bool = False,  # CC_IP
):
    print(f"create {path} with {num_of_blocks} blocks with ")
    blocks: List[FullBlock] = bt.get_consecutive_blocks(
        num_of_blocks,
        seed=seed,
        skip_slots=empty_sub_slots,
        normalized_to_identity_cc_eos=normalized_to_identity_cc_eos,
        normalized_to_identity_icc_eos=normalized_to_identity_icc_eos,
        normalized_to_identity_cc_sp=normalized_to_identity_cc_sp,
        normalized_to_identity_cc_ip=normalized_to_identity_cc_ip,
    )
    block_bytes_list: List[bytes] = []
    for block in blocks:
        block_bytes_list.append(bytes(block))
    bytes_fn = pickle.dumps(block_bytes_list)
    path.write_bytes(bytes_fn)
    return blocks
