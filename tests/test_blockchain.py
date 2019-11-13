import asyncio
import time
from typing import Any, Dict

import pytest
from blspy import PrivateKey

from src.blockchain import Blockchain, ReceiveBlockResult
from src.consensus.constants import constants

from src.types.coinbase import CoinbaseInfo
from src.types.body import Body
from src.types.proof_of_space import ProofOfSpace
from src.types.header import Header
from src.types.header_block import HeaderBlock
from src.types.full_block import FullBlock
from src.types.header import HeaderData
from src.blockchain import Blockchain, ReceiveBlockResult
from src.db.database import FullNodeStore
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
    "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
}
test_constants["GENESIS_BLOCK"] = bytes(
    bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
)
# test_constants["GENESIS_BLOCK"] = b'\x15N3\xd3\xf9H\xc2K\x96\xfe\xf2f\xa2\xbf\x87\x0e\x0f,\xd0\xd4\x0f6s\xb1".\\\xf5\x8a\xb4\x03\x84\x8e\xf9\xbb\xa1\xca\xdef3:\xe4?\x0c\xe5\xc6\x12\x80\x17\xd2\xcc\xd7\xb4m\x94\xb7V\x959\xed4\x89\x04b\x08\x07^\xca`\x8f#%\xe9\x9c\x9d\x86y\x10\x96W\x9d\xce\xc1\x15r\x97\x91U\n\x11<\xdf\xb2\xfc\xfb<\x13\x00\x00\x00\x98\xf4\x88\xcb\xb2MYo]\xaf \xd8a>\x06\xfe\xc8F\x8d\x15\x90\x15\xbb\x04\xd48\x10\xc6\xd8b\x82\x88\x7fx<\xe5\xe6\x8b\x8f\x84\xdd\x1cU"\x83\xfb7\x9d`\xb0I\xb3\xbe;bvE\xc6\x92\xdd\xbe\x988\xe9y;\xc6.\xa1\xce\x94\xdc\xd8\xab\xaf\xba\x8f\xd8r\x8br\xc8\xa0\xac\xc0\xe9T\x87\x08\x08\x8b#-\xb6o\xf0\x1f\x0bzv\xb3\x81\x1a\xd4\xf7\x01\xdf\xc5A\x11\xe0\x0c\xc0\x87\xa6\xc2v\xbbR\xc4{"\xa5\xe5\xe0bx7\xfa\n\xae\xea\xfe\x02\xac\xef\xec\xd1\xc2\xc55\x06{\xe1\x0c\xb2\x99q\xd7\xd8\xcb\x97\x86\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x1f\xeb\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Y\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x007\x03\x00\x00\x004\x00\x8c\xff\xc3\x00\x00\x00\x00\x00\x00\x01T\x00>\xff\xe3\x00\x80\x00[\x00\x00\x00\x00\x00\x00\x05R\x00\x08\x00\x05\x00j\xff\xfd\x00\x00\x00\x00\x00\x00\x17\xf0\x00j\xff\x99\x00j\x00\x03\x01\x03\xa1\xde8\x0f\xb75VB\xf6"`\x94\xc7\x0b\xaa\x1f\xa2Nv\x8a\xf9\xc9\x9a>\x13\xa3a\xc8\x0c\xcb?\x968\xc7\xeb\xc3\x10a\x1a\xa7\xfb\x85\xa7iu\x14`\x8f\x90\x16o\x97\xd5\t\xa4,\xe5\xed\xe1\x15\x86<\x9d\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x05\x00\x00\x00\x00\x00\x00\x1f\xeb\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00]\xbf\xd7f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x03\xa1\xde8\x0f\xb75VB\xf6"`\x94\xc7\x0b\xaa\x1f\xa2Nv\x8a\xf9\xc9\x9a>\x13\xa3a\xc8\x0c\xcb?\x13\x16J\xe5\xfc\xa9\x06\xe8A\xe9\xc0Ql\xfb\xaeF\xcd\xd6\xa7\x8ei\xc4\xfa\xd4i\x84\xee\xc9\xe2\xaa\xa4f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00OB!\x81)\xf0l\xbcg\xa3^\xef\x0e\xfc\xb7\x02\x80\xe4\xa9NO\x89\xa0\t\xc3C\xd9\xda\xff\xd7\t\xeebfC&8\x9c+n$\x00\xa4\xe85\x19\xb0\xf6\x18\xa1\xeeR\xae\xec \x82k\xe0v@;\x1c\xc14PMh\xfb\xe3\x1c\xbf\x84O\xcd\xbc\xc4\xb8\xeabz`\xf7\x06;\xf6q\x8b,\x18\tf~\xd1\x11l#\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n\x8b)\xaa\x96x8\xd76J\xa6\x8b[\x98\t\xe0\\\xe3^7qD\x8c\xf5q\x08\xf2\xa2\xc9\xb03mvU\x1a\xe2\x181\x88\xfe\t\x03?\x12\xadj\x9d\xe8K\xb8!\xee\xe7e8\x82\xfb$\xf0Y\xfaJ\x10\x1f\x1a\xe5\xe9\xa8\xbb\xea\x87\xfc\xb12y\x94\x8d,\x16\xe4C\x02\xba\xe6\xac\x94{\xc4c\x07(\xb8\xeb\xab\xe3\xcfy{6\x98\t\xf4\x8fm\xd62\x85\x87\xb0\x03f\x01B]\xe3\xc6\x13l6\x8d\x0e\x18\xc64%\x97\x1a\xa6\xf4\x8b)\xaa\x96x8\xd76J\xa6\x8b[\x98\t\xe0\\\xe3^7qD\x8c\xf5q\x08\xf2\xa2\xc9\xb03mv\x00\x00\x00\x00\x00\x00\x00\x00\x00_\xec\xebf\xff\xc8o8\xd9Rxlmily\xc2\xdb\xc29\xddN\x91\xb4g)\xd7:\'\xfbW\xe9'


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


class TestGenesisBlock:
    @pytest.mark.asyncio
    async def test_basic_blockchain(self):
        store = FullNodeStore("fndb_test")
        await store._clear_database()
        bc1: Blockchain = Blockchain(store)
        await bc1.initialize()
        assert len(bc1.get_current_tips()) == 1
        genesis_block = bc1.get_current_tips()[0]
        assert genesis_block.height == 0
        assert genesis_block.challenge
        assert (await bc1.get_header_blocks_by_height([uint64(0)], genesis_block.header_hash))[0] == genesis_block
        assert (await bc1.get_next_difficulty(genesis_block.header_hash)) == genesis_block.challenge.total_weight
        assert await bc1.get_next_ips(genesis_block.header_hash) > 0


class TestBlockValidation:
    @pytest.fixture(scope="module")
    async def initial_blockchain(self):
        """
        Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
        """
        store = FullNodeStore("fndb_test")
        await store._clear_database()
        blocks = bt.get_consecutive_blocks(test_constants, 10, [], 10)
        b: Blockchain = Blockchain(store, test_constants)
        await b.initialize()
        for i in range(1, 9):
            assert (
                await b.receive_block(blocks[i])
            ) == ReceiveBlockResult.ADDED_TO_HEAD
        return (blocks, b)

    @pytest.mark.asyncio
    async def test_prev_pointer(self, initial_blockchain):
        blocks, b = initial_blockchain
        block_bad = FullBlock(HeaderBlock(
                blocks[9].header_block.proof_of_space,
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                Header(HeaderData(
                        bytes([1]*32),
                        blocks[9].header_block.header.data.timestamp,
                        blocks[9].header_block.header.data.filter_hash,
                        blocks[9].header_block.header.data.proof_of_space_hash,
                        blocks[9].header_block.header.data.body_hash,
                        blocks[9].header_block.header.data.extension_data
                ), blocks[9].header_block.header.harvester_signature)
                ), blocks[9].body)
        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.DISCONNECTED_BLOCK


    @pytest.mark.asyncio
    async def test_timestamp(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        block_bad = FullBlock(HeaderBlock(
                blocks[9].header_block.proof_of_space,
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                Header(HeaderData(
                        blocks[9].header_block.header.data.prev_header_hash,
                        blocks[9].header_block.header.data.timestamp - 1000,
                        blocks[9].header_block.header.data.filter_hash,
                        blocks[9].header_block.header.data.proof_of_space_hash,
                        blocks[9].header_block.header.data.body_hash,
                        blocks[9].header_block.header.data.extension_data
                ), blocks[9].header_block.header.harvester_signature)
                ), blocks[9].body)
        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

        # Time too far in the future
        block_bad = FullBlock(HeaderBlock(
                blocks[9].header_block.proof_of_space,
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                Header(HeaderData(
                        blocks[9].header_block.header.data.prev_header_hash,
                        uint64(int(time.time() + 3600 * 3)),
                        blocks[9].header_block.header.data.filter_hash,
                        blocks[9].header_block.header.data.proof_of_space_hash,
                        blocks[9].header_block.header.data.body_hash,
                        blocks[9].header_block.header.data.extension_data
                ), blocks[9].header_block.header.harvester_signature)
                ), blocks[9].body)

        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_body_hash(self, initial_blockchain):
        blocks, b = initial_blockchain
        block_bad = FullBlock(HeaderBlock(
                blocks[9].header_block.proof_of_space,
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                Header(HeaderData(
                        blocks[9].header_block.header.data.prev_header_hash,
                        blocks[9].header_block.header.data.timestamp,
                        blocks[9].header_block.header.data.filter_hash,
                        blocks[9].header_block.header.data.proof_of_space_hash,
                        bytes([1]*32),
                        blocks[9].header_block.header.data.extension_data
                ), blocks[9].header_block.header.harvester_signature)
                ), blocks[9].body)

        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_harvester_signature(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        block_bad = FullBlock(HeaderBlock(
                blocks[9].header_block.proof_of_space,
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                Header(
                        blocks[9].header_block.header.data,
                        PrivateKey.from_seed(b'0').sign_prepend(b"random junk"))
                ), blocks[9].body)
        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_invalid_pos(self, initial_blockchain):
        blocks, b = initial_blockchain

        bad_pos = blocks[9].header_block.proof_of_space.proof
        bad_pos[0] = (bad_pos[0] + 1) % 256
        # Proof of space invalid
        block_bad = FullBlock(HeaderBlock(
                ProofOfSpace(
                    blocks[9].header_block.proof_of_space.challenge_hash,
                    blocks[9].header_block.proof_of_space.pool_pubkey,
                    blocks[9].header_block.proof_of_space.plot_pubkey,
                    blocks[9].header_block.proof_of_space.size,
                    bad_pos
                ),
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                blocks[9].header_block.header
        ), blocks[9].body)
        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_invalid_coinbase_height(self, initial_blockchain):
        blocks, b = initial_blockchain

        # Coinbase height invalid
        block_bad = FullBlock(blocks[9].header_block, Body(
                CoinbaseInfo(
                    uint32(3),
                    blocks[9].body.coinbase.amount,
                    blocks[9].body.coinbase.puzzle_hash,
                ),
                blocks[9].body.coinbase_signature,
                blocks[9].body.fees_target_info,
                blocks[9].body.aggregated_signature,
                blocks[9].body.solutions_generator,
                blocks[9].body.cost
        ))
        assert (await b.receive_block(block_bad)) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_difficulty_change(self):
        num_blocks = 30
        # Make it 5x faster than target time
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 2)

        store = FullNodeStore("fndb_test")
        await store._clear_database()
        b: Blockchain = Blockchain(store, test_constants)
        await b.initialize()
        for i in range(1, num_blocks):
            assert (
                await b.receive_block(blocks[i])
            ) == ReceiveBlockResult.ADDED_TO_HEAD

        diff_25 = await b.get_next_difficulty(blocks[24].header_hash)
        diff_26 = await b.get_next_difficulty(blocks[25].header_hash)
        diff_27 = await b.get_next_difficulty(blocks[26].header_hash)

        assert diff_26 == diff_25
        assert diff_27 > diff_26
        assert (diff_27 / diff_26) <= test_constants["DIFFICULTY_FACTOR"]

        assert (await b.get_next_ips(blocks[1].header_hash)) == constants["VDF_IPS_STARTING"]
        assert (await b.get_next_ips(blocks[24].header_hash)) == (await b.get_next_ips(blocks[23].header_hash))
        assert (await b.get_next_ips(blocks[25].header_hash)) == (await b.get_next_ips(blocks[24].header_hash))
        assert (await b.get_next_ips(blocks[26].header_hash)) > (await b.get_next_ips(blocks[25].header_hash))
        assert (await b.get_next_ips(blocks[27].header_hash)) == (await b.get_next_ips(blocks[26].header_hash))


class TestReorgs():
    @pytest.mark.asyncio
    async def test_basic_reorg(self):
        blocks = bt.get_consecutive_blocks(test_constants, 100, [], 9)
        store = FullNodeStore("fndb_test")
        await store._clear_database()
        b: Blockchain = Blockchain(store, test_constants)
        await b.initialize()

        for block in blocks:
            await b.receive_block(block)
        assert b.get_current_tips()[0].height == 100

        blocks_reorg_chain = bt.get_consecutive_blocks(
            test_constants, 30, blocks[:90], 9, b"1"
        )
        for reorg_block in blocks_reorg_chain:
            result = await b.receive_block(reorg_block)
            if reorg_block.height < 90:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height < 99:
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
            elif reorg_block.height >= 100:
                assert result == ReceiveBlockResult.ADDED_TO_HEAD
        assert b.get_current_tips()[0].height == 119

    @pytest.mark.asyncio
    async def test_reorg_from_genesis(self):
        blocks = bt.get_consecutive_blocks(test_constants, 20, [], 9, b"0")
        store = FullNodeStore("fndb_test")
        await store._clear_database()
        b: Blockchain = Blockchain(store, test_constants)
        await b.initialize()
        for block in blocks:
            await b.receive_block(block)
        assert b.get_current_tips()[0].height == 20

        # Reorg from genesis
        blocks_reorg_chain = bt.get_consecutive_blocks(
            test_constants, 21, [blocks[0]], 9, b"1"
        )
        for reorg_block in blocks_reorg_chain:
            result = await b.receive_block(reorg_block)
            if reorg_block.height == 0:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height < 19:
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
            else:
                assert result == ReceiveBlockResult.ADDED_TO_HEAD
        assert b.get_current_tips()[0].height == 21

        # Reorg back to original branch
        blocks_reorg_chain_2 = bt.get_consecutive_blocks(
            test_constants, 3, blocks, 9, b"3"
        )
        await b.receive_block(
            blocks_reorg_chain_2[20]
        ) == ReceiveBlockResult.ADDED_AS_ORPHAN
        assert (
            await b.receive_block(blocks_reorg_chain_2[21])
        ) == ReceiveBlockResult.ADDED_TO_HEAD
        assert (
            await b.receive_block(blocks_reorg_chain_2[22])
        ) == ReceiveBlockResult.ADDED_TO_HEAD

    @pytest.mark.asyncio
    async def test_lca(self):
        blocks = bt.get_consecutive_blocks(test_constants, 5, [], 9, b"0")
        store = FullNodeStore("fndb_test")
        await store._clear_database()
        b: Blockchain = Blockchain(store, test_constants)
        await b.initialize()
        for block in blocks:
            await b.receive_block(block)

        assert b.lca_block == blocks[3]
        block_5_2 = bt.get_consecutive_blocks(test_constants, 1, blocks[:5], 9, b"1")[5]
        block_5_3 = bt.get_consecutive_blocks(test_constants, 1, blocks[:5], 9, b"2")[5]

        await b.receive_block(block_5_2)
        assert b.lca_block == blocks[4]
        await b.receive_block(block_5_3)
        assert b.lca_block == blocks[4]

        reorg = bt.get_consecutive_blocks(test_constants, 6, [], 9, b"3")
        for block in reorg:
            await b.receive_block(block)
        assert b.lca_block == blocks[0]
