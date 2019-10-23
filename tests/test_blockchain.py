import time
import pytest
import asyncio
from typing import Dict, Any
from blspy import PrivateKey
from src.consensus.constants import constants
from src.types.coinbase import CoinbaseInfo
from src.types.block_body import BlockBody
from src.types.proof_of_space import ProofOfSpace
from src.types.block_header import BlockHeader
from src.types.trunk_block import TrunkBlock
from src.types.full_block import FullBlock
from src.types.block_header import BlockHeaderData
from src.blockchain import Blockchain, ReceiveBlockResult
from src.store.full_node_store import FullNodeStore
from src.util.ints import uint64, uint32
from tests.block_tools import BlockTools


bt = BlockTools()

test_constants: Dict[str, Any] = {
    "DIFFICULTY_STARTING": 5,
    "DISCRIMINANT_SIZE_BITS": 16,
    "BLOCK_TIME_TARGET": 10,
    "MIN_BLOCK_TIME": 2,
    "DIFFICULTY_FACTOR": 3,
    "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
    "DIFFICULTY_WARP_FACTOR": 4,  # DELAY divides EPOCH in order to warp efficiently.
    "DIFFICULTY_DELAY": 3  # EPOCH / WARP_FACTOR
}
test_constants["GENESIS_BLOCK"] = bt.create_genesis_block(test_constants, bytes([0]*32), uint64(0)).serialize()


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


class TestGenesisBlock():
    @pytest.mark.asyncio
    async def test_basic_blockchain(self):
        store = FullNodeStore()
        await store.initialize()
        bc1: Blockchain = Blockchain(store)
        await bc1.initialize()
        assert len(bc1.get_current_heads()) == 1
        genesis_block = bc1.get_current_heads()[0]
        assert genesis_block.height == 0
        assert genesis_block.challenge
        assert (await bc1.get_trunk_blocks_by_height([uint64(0)], genesis_block.header_hash))[0] == genesis_block
        assert (await bc1.get_next_difficulty(genesis_block.header_hash)) == genesis_block.challenge.total_weight
        assert await bc1.get_next_ips(genesis_block.header_hash) > 0


class TestBlockValidation():
    @pytest.fixture(scope="module")
    async def initial_blockchain(self):
        """
        Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
        """
        store = FullNodeStore()
        await store.initialize()
        blocks = bt.get_consecutive_blocks(test_constants, 10, [], 10)
        b: Blockchain = Blockchain(store, test_constants)
        await b.initialize()
        for i in range(1, 9):
            assert (await b.receive_block(blocks[i])) == ReceiveBlockResult.ADDED_TO_HEAD
        return (blocks, b)

    @pytest.mark.asyncio
    async def test_prev_pointer(self, initial_blockchain):
        blocks, b = initial_blockchain
        block_bad = FullBlock(TrunkBlock(
                blocks[9].trunk_block.proof_of_space,
                blocks[9].trunk_block.proof_of_time,
                blocks[9].trunk_block.challenge,
                BlockHeader(BlockHeaderData(
                        bytes([1]*32),
                        blocks[9].trunk_block.header.data.timestamp,
                        blocks[9].trunk_block.header.data.filter_hash,
                        blocks[9].trunk_block.header.data.proof_of_space_hash,
                        blocks[9].trunk_block.header.data.body_hash,
                        blocks[9].trunk_block.header.data.extension_data
                ), blocks[9].trunk_block.header.plotter_signature)
                ), blocks[9].body)
        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_timestamp(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        block_bad = FullBlock(TrunkBlock(
                blocks[9].trunk_block.proof_of_space,
                blocks[9].trunk_block.proof_of_time,
                blocks[9].trunk_block.challenge,
                BlockHeader(BlockHeaderData(
                        blocks[9].trunk_block.header.data.prev_header_hash,
                        blocks[9].trunk_block.header.data.timestamp - 1000,
                        blocks[9].trunk_block.header.data.filter_hash,
                        blocks[9].trunk_block.header.data.proof_of_space_hash,
                        blocks[9].trunk_block.header.data.body_hash,
                        blocks[9].trunk_block.header.data.extension_data
                ), blocks[9].trunk_block.header.plotter_signature)
                ), blocks[9].body)
        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

        # Time too far in the future
        block_bad = FullBlock(TrunkBlock(
                blocks[9].trunk_block.proof_of_space,
                blocks[9].trunk_block.proof_of_time,
                blocks[9].trunk_block.challenge,
                BlockHeader(BlockHeaderData(
                        blocks[9].trunk_block.header.data.prev_header_hash,
                        uint64(int(time.time() + 3600 * 3)),
                        blocks[9].trunk_block.header.data.filter_hash,
                        blocks[9].trunk_block.header.data.proof_of_space_hash,
                        blocks[9].trunk_block.header.data.body_hash,
                        blocks[9].trunk_block.header.data.extension_data
                ), blocks[9].trunk_block.header.plotter_signature)
                ), blocks[9].body)

        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_body_hash(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        block_bad = FullBlock(TrunkBlock(
                blocks[9].trunk_block.proof_of_space,
                blocks[9].trunk_block.proof_of_time,
                blocks[9].trunk_block.challenge,
                BlockHeader(BlockHeaderData(
                        blocks[9].trunk_block.header.data.prev_header_hash,
                        blocks[9].trunk_block.header.data.timestamp,
                        blocks[9].trunk_block.header.data.filter_hash,
                        blocks[9].trunk_block.header.data.proof_of_space_hash,
                        bytes([1]*32),
                        blocks[9].trunk_block.header.data.extension_data
                ), blocks[9].trunk_block.header.plotter_signature)
                ), blocks[9].body)
        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_plotter_signature(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        block_bad = FullBlock(TrunkBlock(
                blocks[9].trunk_block.proof_of_space,
                blocks[9].trunk_block.proof_of_time,
                blocks[9].trunk_block.challenge,
                BlockHeader(
                        blocks[9].trunk_block.header.data,
                        PrivateKey.from_seed(b'0').sign_prepend(b"random junk"))
                ), blocks[9].body)
        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_invalid_pos(self, initial_blockchain):
        blocks, b = initial_blockchain

        bad_pos = blocks[9].trunk_block.proof_of_space.proof
        bad_pos[0] = (bad_pos[0] + 1) % 256
        # Proof of space invalid
        block_bad = FullBlock(TrunkBlock(
                ProofOfSpace(
                    blocks[9].trunk_block.proof_of_space.pool_pubkey,
                    blocks[9].trunk_block.proof_of_space.plot_pubkey,
                    blocks[9].trunk_block.proof_of_space.size,
                    bad_pos
                ),
                blocks[9].trunk_block.proof_of_time,
                blocks[9].trunk_block.challenge,
                blocks[9].trunk_block.header
        ), blocks[9].body)
        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_invalid_coinbase_height(self, initial_blockchain):
        blocks, b = initial_blockchain

        # Coinbase height invalid
        block_bad = FullBlock(blocks[9].trunk_block, BlockBody(
                CoinbaseInfo(
                        uint32(3),
                        blocks[9].body.coinbase.amount,
                        blocks[9].body.coinbase.puzzle_hash
                ),
                blocks[9].body.coinbase_signature,
                blocks[9].body.fees_target_info,
                blocks[9].body.aggregated_signature,
                blocks[9].body.solutions_generator
        ))
        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_difficulty_change(self):
        num_blocks = 20
        # Make it 5x faster than target time
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 2)

        store = FullNodeStore()
        await store.initialize()
        b: Blockchain = Blockchain(store, test_constants)
        await b.initialize()
        for i in range(1, num_blocks):
            assert (await b.receive_block(blocks[i])) == ReceiveBlockResult.ADDED_TO_HEAD

        diff_13 = await b.get_next_difficulty(blocks[12].header_hash)
        diff_14 = await b.get_next_difficulty(blocks[13].header_hash)
        diff_15 = await b.get_next_difficulty(blocks[14].header_hash)

        assert diff_14 == diff_13
        assert diff_15 > diff_14
        assert (diff_15 / diff_14) <= test_constants["DIFFICULTY_FACTOR"]

        assert (await b.get_next_ips(blocks[1].header_hash)) == constants["VDF_IPS_STARTING"]
        assert (await b.get_next_ips(blocks[12].header_hash)) == (await b.get_next_ips(blocks[11].header_hash))
        assert (await b.get_next_ips(blocks[13].header_hash)) == (await b.get_next_ips(blocks[12].header_hash))
        assert (await b.get_next_ips(blocks[14].header_hash)) > (await b.get_next_ips(blocks[13].header_hash))
        assert (await b.get_next_ips(blocks[15].header_hash)) == (await b.get_next_ips(blocks[14].header_hash))


class TestReorgs():
    @pytest.mark.asyncio
    async def test_basic_reorg(self):
        blocks = bt.get_consecutive_blocks(test_constants, 100, [], 9)
        store = FullNodeStore()
        await store.initialize()
        b: Blockchain = Blockchain(store, test_constants)
        await b.initialize()

        for block in blocks:
            await b.receive_block(block)
        assert b.get_current_heads()[0].height == 100

        blocks_reorg_chain = bt.get_consecutive_blocks(test_constants, 30, blocks[:90], 9, uint64(1))
        for reorg_block in blocks_reorg_chain:
            result = await b.receive_block(reorg_block)
            if reorg_block.height < 90:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height < 99:
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
            elif reorg_block.height >= 100:
                assert result == ReceiveBlockResult.ADDED_TO_HEAD
        assert b.get_current_heads()[0].height == 119

    @pytest.mark.asyncio
    async def test_reorg_from_genesis(self):
        blocks = bt.get_consecutive_blocks(test_constants, 20, [], 9, uint64(0))
        store = FullNodeStore()
        await store.initialize()
        b: Blockchain = Blockchain(store, test_constants)
        await b.initialize()
        for block in blocks:
            await b.receive_block(block)
        assert b.get_current_heads()[0].height == 20

        # Reorg from genesis
        blocks_reorg_chain = bt.get_consecutive_blocks(test_constants, 21, [blocks[0]], 9, uint64(1))
        for reorg_block in blocks_reorg_chain:
            result = await b.receive_block(reorg_block)
            if reorg_block.height == 0:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height < 19:
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
            else:
                assert result == ReceiveBlockResult.ADDED_TO_HEAD
        assert b.get_current_heads()[0].height == 21

        # Reorg back to original branch
        blocks_reorg_chain_2 = bt.get_consecutive_blocks(test_constants, 3, blocks, 9, uint64(3))
        await b.receive_block(blocks_reorg_chain_2[20]) == ReceiveBlockResult.ADDED_AS_ORPHAN
        assert (await b.receive_block(blocks_reorg_chain_2[21])) == ReceiveBlockResult.ADDED_TO_HEAD
        assert (await b.receive_block(blocks_reorg_chain_2[22])) == ReceiveBlockResult.ADDED_TO_HEAD
