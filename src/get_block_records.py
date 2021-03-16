import asyncio
import os
from pathlib import Path

import aiosqlite

from src.consensus.blockchain import Blockchain
from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.full_node.block_store import BlockStore
from src.full_node.coin_store import CoinStore


async def main():
    db_filename = Path(os.path.expanduser("~/.chia/1.0rc6.dev22/db/blockchain_v29_f4c0c9d5b3cd59d6.sqlite"))
    connection = await aiosqlite.connect(db_filename)
    coin_store = await CoinStore.create(connection)
    store = await BlockStore.create(connection)
    bc = await Blockchain.create(coin_store, store, DEFAULT_CONSTANTS)
    recs = await bc.get_block_records_in_range(0, 100000)
    print(len(recs))


asyncio.run(main())
