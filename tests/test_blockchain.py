import asyncio
import time
from typing import Any, Dict

import pytest
from blspy import PrivateKey

from src.blockchain import Blockchain, ReceiveBlockResult
from src.consensus.constants import constants
from src.types.body import Body
from src.types.coinbase import CoinbaseInfo
from src.types.full_block import FullBlock
from src.types.header import Header, HeaderData
from src.types.header_block import HeaderBlock
from src.types.proof_of_space import ProofOfSpace
from src.util.ints import uint8, uint32, uint64
from src.util.errors import BlockNotInBlockchain
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


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestGenesisBlock:
    @pytest.mark.asyncio
    async def test_basic_blockchain(self):
        bc1 = await Blockchain.create({})
        assert len(bc1.get_current_tips()) == 1
        genesis_block = bc1.get_current_tips()[0]
        assert genesis_block.height == 0
        assert genesis_block.challenge
        assert (
            bc1.get_header_hashes_by_height([uint32(0)], genesis_block.header_hash)
        )[0] == genesis_block.header_hash
        assert (
            bc1.get_next_difficulty(genesis_block.header_hash)
        ) == genesis_block.challenge.total_weight
        assert bc1.get_next_ips(bc1.genesis.header_block) > 0


class TestBlockValidation:
    @pytest.fixture(scope="module")
    async def initial_blockchain(self):
        """
        Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
        """
        blocks = bt.get_consecutive_blocks(test_constants, 10, [], 10)
        b: Blockchain = await Blockchain.create({}, test_constants)
        for i in range(1, 9):
            assert (
                await b.receive_block(blocks[i], blocks[i - 1].header_block)
            ) == ReceiveBlockResult.ADDED_TO_HEAD
        return (blocks, b)

    @pytest.mark.asyncio
    async def test_get_header_hashes(self, initial_blockchain):
        blocks, b = initial_blockchain
        header_hashes_1 = b.get_header_hashes_by_height(
            [0, 8, 3], blocks[8].header_hash
        )
        assert header_hashes_1 == [
            blocks[0].header_hash,
            blocks[8].header_hash,
            blocks[3].header_hash,
        ]

        try:
            b.get_header_hashes_by_height([0, 8, 3], blocks[6].header_hash)
            thrown = False
        except ValueError:
            thrown = True
        assert thrown

        try:
            b.get_header_hashes_by_height([0, 8, 3], blocks[9].header_hash)
            thrown_2 = False
        except BlockNotInBlockchain:
            thrown_2 = True
        assert thrown_2

    @pytest.mark.asyncio
    async def test_prev_pointer(self, initial_blockchain):
        blocks, b = initial_blockchain
        block_bad = FullBlock(
            HeaderBlock(
                blocks[9].header_block.proof_of_space,
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                Header(
                    HeaderData(
                        bytes([1] * 32),
                        blocks[9].header_block.header.data.timestamp,
                        blocks[9].header_block.header.data.filter_hash,
                        blocks[9].header_block.header.data.proof_of_space_hash,
                        blocks[9].header_block.header.data.body_hash,
                        blocks[9].header_block.header.data.extension_data,
                    ),
                    blocks[9].header_block.header.harvester_signature,
                ),
            ),
            blocks[9].body,
        )
        assert (
            await b.receive_block(block_bad, blocks[8].header_block)
        ) == ReceiveBlockResult.DISCONNECTED_BLOCK

    @pytest.mark.asyncio
    async def test_timestamp(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        block_bad = FullBlock(
            HeaderBlock(
                blocks[9].header_block.proof_of_space,
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                Header(
                    HeaderData(
                        blocks[9].header_block.header.data.prev_header_hash,
                        blocks[9].header_block.header.data.timestamp - 1000,
                        blocks[9].header_block.header.data.filter_hash,
                        blocks[9].header_block.header.data.proof_of_space_hash,
                        blocks[9].header_block.header.data.body_hash,
                        blocks[9].header_block.header.data.extension_data,
                    ),
                    blocks[9].header_block.header.harvester_signature,
                ),
            ),
            blocks[9].body,
        )
        assert (
            await b.receive_block(block_bad, blocks[8].header_block)
        ) == ReceiveBlockResult.INVALID_BLOCK

        # Time too far in the future
        block_bad = FullBlock(
            HeaderBlock(
                blocks[9].header_block.proof_of_space,
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                Header(
                    HeaderData(
                        blocks[9].header_block.header.data.prev_header_hash,
                        uint64(int(time.time() + 3600 * 3)),
                        blocks[9].header_block.header.data.filter_hash,
                        blocks[9].header_block.header.data.proof_of_space_hash,
                        blocks[9].header_block.header.data.body_hash,
                        blocks[9].header_block.header.data.extension_data,
                    ),
                    blocks[9].header_block.header.harvester_signature,
                ),
            ),
            blocks[9].body,
        )

        assert (
            await b.receive_block(block_bad, blocks[8].header_block)
        ) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_body_hash(self, initial_blockchain):
        blocks, b = initial_blockchain
        block_bad = FullBlock(
            HeaderBlock(
                blocks[9].header_block.proof_of_space,
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                Header(
                    HeaderData(
                        blocks[9].header_block.header.data.prev_header_hash,
                        blocks[9].header_block.header.data.timestamp,
                        blocks[9].header_block.header.data.filter_hash,
                        blocks[9].header_block.header.data.proof_of_space_hash,
                        bytes([1] * 32),
                        blocks[9].header_block.header.data.extension_data,
                    ),
                    blocks[9].header_block.header.harvester_signature,
                ),
            ),
            blocks[9].body,
        )

        assert (
            await b.receive_block(block_bad, blocks[8].header_block)
        ) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_harvester_signature(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        block_bad = FullBlock(
            HeaderBlock(
                blocks[9].header_block.proof_of_space,
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                Header(
                    blocks[9].header_block.header.data,
                    PrivateKey.from_seed(b"0").sign_prepend(b"random junk"),
                ),
            ),
            blocks[9].body,
        )
        assert (
            await b.receive_block(block_bad, blocks[8].header_block)
        ) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_invalid_pos(self, initial_blockchain):
        blocks, b = initial_blockchain

        bad_pos = [i for i in blocks[9].header_block.proof_of_space.proof]
        bad_pos[0] = uint8((bad_pos[0] + 1) % 256)
        # Proof of space invalid
        block_bad = FullBlock(
            HeaderBlock(
                ProofOfSpace(
                    blocks[9].header_block.proof_of_space.challenge_hash,
                    blocks[9].header_block.proof_of_space.pool_pubkey,
                    blocks[9].header_block.proof_of_space.plot_pubkey,
                    blocks[9].header_block.proof_of_space.size,
                    bad_pos,
                ),
                blocks[9].header_block.proof_of_time,
                blocks[9].header_block.challenge,
                blocks[9].header_block.header,
            ),
            blocks[9].body,
        )
        assert (
            await b.receive_block(block_bad, blocks[8].header_block)
        ) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_invalid_coinbase_height(self, initial_blockchain):
        blocks, b = initial_blockchain

        # Coinbase height invalid
        block_bad = FullBlock(
            blocks[9].header_block,
            Body(
                CoinbaseInfo(
                    uint32(3),
                    blocks[9].body.coinbase.amount,
                    blocks[9].body.coinbase.puzzle_hash,
                ),
                blocks[9].body.coinbase_signature,
                blocks[9].body.fees_target_info,
                blocks[9].body.aggregated_signature,
                blocks[9].body.solutions_generator,
                blocks[9].body.cost,
            ),
        )
        assert (
            await b.receive_block(block_bad, blocks[8].header_block)
        ) == ReceiveBlockResult.INVALID_BLOCK

    @pytest.mark.asyncio
    async def test_difficulty_change(self):
        num_blocks = 30
        # Make it 5x faster than target time
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 2)

        b: Blockchain = await Blockchain.create({}, test_constants)
        for i in range(1, num_blocks):
            assert (
                await b.receive_block(blocks[i], blocks[i - 1].header_block)
            ) == ReceiveBlockResult.ADDED_TO_HEAD

        diff_25 = b.get_next_difficulty(blocks[24].header_hash)
        diff_26 = b.get_next_difficulty(blocks[25].header_hash)
        diff_27 = b.get_next_difficulty(blocks[26].header_hash)

        assert diff_26 == diff_25
        assert diff_27 > diff_26
        assert (diff_27 / diff_26) <= test_constants["DIFFICULTY_FACTOR"]

        assert (b.get_next_ips(blocks[1].header_block)) == constants["VDF_IPS_STARTING"]
        assert (b.get_next_ips(blocks[24].header_block)) == (
            b.get_next_ips(blocks[23].header_block)
        )
        assert (b.get_next_ips(blocks[25].header_block)) == (
            b.get_next_ips(blocks[24].header_block)
        )
        assert (b.get_next_ips(blocks[26].header_block)) > (
            b.get_next_ips(blocks[25].header_block)
        )
        assert (b.get_next_ips(blocks[27].header_block)) == (
            b.get_next_ips(blocks[26].header_block)
        )


class TestReorgs:
    @pytest.mark.asyncio
    async def test_basic_reorg(self):
        blocks = bt.get_consecutive_blocks(test_constants, 100, [], 9)
        b: Blockchain = await Blockchain.create({}, test_constants)

        for i in range(1, len(blocks)):
            await b.receive_block(blocks[i], blocks[i - 1].header_block)
        assert b.get_current_tips()[0].height == 100

        blocks_reorg_chain = bt.get_consecutive_blocks(
            test_constants, 30, blocks[:90], 9, b"1"
        )
        for i in range(1, len(blocks_reorg_chain)):
            reorg_block = blocks_reorg_chain[i]
            result = await b.receive_block(
                reorg_block, blocks_reorg_chain[i - 1].header_block
            )
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
        print(len(blocks))
        b: Blockchain = await Blockchain.create({}, test_constants)
        for i in range(1, len(blocks)):
            await b.receive_block(blocks[i], blocks[i - 1].header_block)
        assert b.get_current_tips()[0].height == 20

        # Reorg from genesis
        blocks_reorg_chain = bt.get_consecutive_blocks(
            test_constants, 21, [blocks[0]], 9, b"1"
        )
        for i in range(1, len(blocks_reorg_chain)):
            reorg_block = blocks_reorg_chain[i]
            result = await b.receive_block(
                reorg_block, blocks_reorg_chain[i - 1].header_block
            )
            if reorg_block.height == 0:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height < 19:
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
            else:
                assert result == ReceiveBlockResult.ADDED_TO_HEAD
        assert b.get_current_tips()[0].height == 21

        # Reorg back to original branch
        blocks_reorg_chain_2 = bt.get_consecutive_blocks(
            test_constants, 3, blocks[:-1], 9, b"3"
        )
        assert (
            await b.receive_block(
                blocks_reorg_chain_2[20], blocks_reorg_chain_2[19].header_block
            )
            == ReceiveBlockResult.ADDED_AS_ORPHAN
        )
        assert (
            await b.receive_block(
                blocks_reorg_chain_2[21], blocks_reorg_chain_2[20].header_block
            )
        ) == ReceiveBlockResult.ADDED_TO_HEAD
        assert (
            await b.receive_block(
                blocks_reorg_chain_2[22], blocks_reorg_chain_2[21].header_block
            )
        ) == ReceiveBlockResult.ADDED_TO_HEAD

    @pytest.mark.asyncio
    async def test_lca(self):
        blocks = bt.get_consecutive_blocks(test_constants, 5, [], 9, b"0")
        b: Blockchain = await Blockchain.create({}, test_constants)
        for i in range(1, len(blocks)):
            await b.receive_block(blocks[i], blocks[i - 1].header_block)

        assert b.lca_block.header_hash == blocks[3].header_block.header_hash
        block_5_2 = bt.get_consecutive_blocks(test_constants, 1, blocks[:5], 9, b"1")
        block_5_3 = bt.get_consecutive_blocks(test_constants, 1, blocks[:5], 9, b"2")

        await b.receive_block(block_5_2[5], block_5_2[4].header_block)
        assert b.lca_block.header_hash == blocks[4].header_block.header_hash
        await b.receive_block(block_5_3[5], block_5_3[4].header_block)
        assert b.lca_block.header_hash == blocks[4].header_block.header_hash

        reorg = bt.get_consecutive_blocks(test_constants, 6, [], 9, b"3")
        for i in range(1, len(reorg)):
            await b.receive_block(reorg[i], reorg[i - 1].header_block)
        assert b.lca_block.header_hash == blocks[0].header_block.header_hash

    @pytest.mark.asyncio
    async def test_get_header_hashes(self):
        blocks = bt.get_consecutive_blocks(test_constants, 5, [], 9, b"0")
        b: Blockchain = await Blockchain.create({}, test_constants)
        for i in range(1, len(blocks)):
            await b.receive_block(blocks[i], blocks[i - 1].header_block)
        header_hashes = b.get_header_hashes(blocks[-1].header_hash)
        assert len(header_hashes) == 6
        print(header_hashes)
        print([block.header_hash for block in blocks])
        assert header_hashes == [block.header_hash for block in blocks]
