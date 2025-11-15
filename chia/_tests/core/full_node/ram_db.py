from __future__ import annotations

import contextlib
import random
from collections.abc import AsyncIterator
from pathlib import Path

from chia_rs import ConsensusConstants

from chia.consensus.blockchain import Blockchain
from chia.full_node.consensus_store_sqlite3 import ConsensusStoreSQLite3
from chia.util.db_wrapper import DBWrapper2


@contextlib.asynccontextmanager
async def create_ram_blockchain(
    consensus_constants: ConsensusConstants,
) -> AsyncIterator[tuple[DBWrapper2, Blockchain]]:
    uri = f"file:db_{random.randint(0, 99999999)}?mode=memory&cache=shared"
    async with DBWrapper2.managed(database=uri, uri=True, reader_count=1, db_version=2) as db_wrapper:
        consensus_store = await ConsensusStoreSQLite3.create(db_wrapper, Path("."))
        blockchain = await Blockchain.create(consensus_store, consensus_constants, 2)
        try:
            yield db_wrapper, blockchain
        finally:
            blockchain.shut_down()
