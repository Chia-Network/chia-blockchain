from __future__ import annotations

import contextlib
import random
from pathlib import Path
from typing import AsyncIterator, Tuple

from chia.consensus.blockchain import Blockchain
from chia.consensus.constants import ConsensusConstants
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.util.db_wrapper import DBWrapper2


@contextlib.asynccontextmanager
async def create_ram_blockchain(
    consensus_constants: ConsensusConstants,
) -> AsyncIterator[Tuple[DBWrapper2, Blockchain]]:
    uri = f"file:db_{random.randint(0, 99999999)}?mode=memory&cache=shared"
    async with DBWrapper2.managed(database=uri, uri=True, reader_count=1, db_version=2) as db_wrapper:
        block_store = await BlockStore.create(db_wrapper)
        coin_store = await CoinStore.create(db_wrapper)
        blockchain = await Blockchain.create(coin_store, block_store, consensus_constants, Path("."), 2)
        try:
            yield db_wrapper, blockchain
        finally:
            blockchain.shut_down()
