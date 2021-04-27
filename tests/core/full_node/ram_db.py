import aiosqlite

from chia.consensus.blockchain import Blockchain
from chia.consensus.constants import ConsensusConstants
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.util.db_wrapper import DBWrapper


async def create_ram_blockchain(consensus_constants: ConsensusConstants):
    connection = await aiosqlite.connect(":memory:")
    db_wrapper = DBWrapper(connection)
    block_store = await BlockStore.create(db_wrapper)
    coin_store = await CoinStore.create(db_wrapper)
    return await Blockchain.create(coin_store, block_store, consensus_constants)
