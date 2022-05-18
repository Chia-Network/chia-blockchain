import logging
import multiprocessing
import time
from pathlib import Path
from chia.consensus.blockchain import Blockchain
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.full_node.weight_proof_v2 import WeightProofHandlerV2
from chia.consensus.constants import ConsensusConstants
from chia.server.start_full_node import SERVICE_NAME
from chia.util.config import process_config_start_method, load_config
from chia.util.db_synchronous import db_synchronous_on
from chia.util.db_version import lookup_db_version
from chia.util.db_wrapper import DBWrapper2
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint32
from chia.util.path import path_from_root
from typing import Tuple
import aiosqlite


async def build_weight_proof_v2_database(path: Path) -> None:
    blockchain, updated_constants, db_wrapper = await get_blockchain(path)
    wphv2 = WeightProofHandlerV2(updated_constants, blockchain)
    try:
        await create_sub_epoch_segments(wphv2)
    finally:
        blockchain.shut_down()
        await db_wrapper.close()


async def check_weight_proof_v2_database(path: Path) -> bool:
    blockchain, updated_constants, db_wrapper = await get_blockchain(path)
    wphv2 = WeightProofHandlerV2(updated_constants, blockchain)
    try:
        v2_wp_db = await wphv2.check_prev_sub_epoch_segments()
    finally:
        blockchain.shut_down()
        await db_wrapper.close()
    return v2_wp_db


async def get_blockchain(path: Path = DEFAULT_ROOT_PATH) -> Tuple[Blockchain, ConsensusConstants, DBWrapper2]:
    config = load_config(path, "config.yaml", SERVICE_NAME)
    overrides = config["network_overrides"]["constants"]["mainnet"]
    updated_constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
    db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])
    db_path = path_from_root(DEFAULT_ROOT_PATH, db_path_replaced)
    db_connection = await aiosqlite.connect(db_path)
    db_version: int = await lookup_db_version(db_connection)
    db_wrapper = DBWrapper2(db_connection, db_version=db_version)
    # add reader threads for the DB
    for i in range(config.get("db_readers", 4)):
        c = await aiosqlite.connect(db_path)
        await db_wrapper.add_connection(c)
    await (await db_connection.execute("pragma journal_mode=wal")).close()
    db_sync = db_synchronous_on(config.get("db_sync", "auto"), db_path)
    await (await db_connection.execute("pragma synchronous={}".format(db_sync))).close()
    block_store = await BlockStore.create(db_wrapper)
    hint_store = await HintStore.create(db_wrapper)
    coin_store = await CoinStore.create(db_wrapper)
    reserved_cores = config.get("reserved_cores", 0)
    single_threaded = config.get("single_threaded", False)
    multiprocessing_start_method = process_config_start_method(config=config, log=logging.getLogger())
    multiprocessing_context = multiprocessing.get_context(method=multiprocessing_start_method)
    blockchain = await Blockchain.create(
        coin_store=coin_store,
        block_store=block_store,
        consensus_constants=updated_constants,
        hint_store=hint_store,
        blockchain_dir=db_path.parent,
        reserved_cores=reserved_cores,
        multiprocessing_context=multiprocessing_context,
        single_threaded=single_threaded,
    )

    return blockchain, updated_constants, db_wrapper


async def create_sub_epoch_segments(wph: WeightProofHandlerV2) -> None:
    """
    iterates through all sub epochs creates the corresponding segments
    and persists to the db segment table
    """
    peak_height = wph.blockchain.get_peak_height()
    if peak_height is None:
        print("FAILED: empty blockchain")
        return None

    summary_heights = wph.blockchain.get_ses_heights()
    prev_ses_block = await wph.blockchain.get_block_record_from_db(wph.height_to_hash(uint32(0)))
    if prev_ses_block is None:
        print("FAILED: genesis block is missing")
        return None

    ses_blocks = await wph.blockchain.get_block_records_at(summary_heights)
    if ses_blocks is None:
        return None

    for sub_epoch_n, ses_block in enumerate(ses_blocks):
        print(f"handle sub epoch {sub_epoch_n} out of {len(ses_blocks)}")
        if ses_block.height > peak_height:
            break
        if ses_block is None or ses_block.sub_epoch_summary_included is None:
            print(f"FAILED: error while building segments for sub epoch {sub_epoch_n}")
            return None
        print(f"create segments for sub epoch {sub_epoch_n}")
        start = time.time()
        await wph.create_persist_sub_epoch(prev_ses_block, ses_block, uint32(sub_epoch_n))
        print(f"took {time.time() - start} sec to handle sub epoch {sub_epoch_n}")
        prev_ses_block = ses_block
    print("finished creating Wieht proof v2 segments")
    return None
