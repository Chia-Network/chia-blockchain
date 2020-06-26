import asyncio
import time
from typing import Any, Dict
from pathlib import Path

import aiosqlite
import pytest
from blspy import PrivateKey

from src.full_node.blockchain import Blockchain, ReceiveBlockResult
from src.types.full_block import FullBlock
from src.types.header import Header, HeaderData
from src.types.proof_of_space import ProofOfSpace
from src.util.ints import uint8, uint64
from src.consensus.constants import ConsensusConstants
from tests.block_tools import BlockTools
from src.util.errors import Err
from src.consensus.coinbase import create_coinbase_coin_and_signature
from src.types.sized_bytes import bytes32
from src.full_node.block_store import BlockStore
from src.full_node.coin_store import CoinStore
from src.consensus.find_fork_point import find_fork_point_in_chain
from tests.block_tools import BlockTools
from tests.make_test_constants import make_test_constants_with_genesis

bt = BlockTools()

test_constants: ConsensusConstants = make_test_constants_with_genesis({
        "DIFFICULTY_STARTING": 1,
        "DISCRIMINANT_SIZE_BITS": 8,
        "BLOCK_TIME_TARGET": 10,
        "DIFFICULTY_EPOCH": 6,  # The number of blocks per epoch
        "DIFFICULTY_WARP_FACTOR": 3,
        "DIFFICULTY_DELAY": 2,  # EPOCH / WARP_FACTOR
        "MIN_ITERS_STARTING": 50 * 1,
})
test_constants_dict: Dict[str, Any] = test_constants.copy()


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestGenesisBlock:
    @pytest.mark.asyncio
    async def test_basic_blockchain(self):
        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)
        store = await BlockStore.create(connection)
        bc1 = await Blockchain.create(coin_store, store, test_constants)
        assert len(bc1.get_current_tips()) == 1
        genesis_block = bc1.get_current_tips()[0]
        assert genesis_block.height == 0
        assert (bc1.get_next_difficulty(genesis_block)) == genesis_block.weight
        assert bc1.get_next_min_iters(bc1.genesis) > 0

        await connection.close()
        bc1.shut_down()


class TestBlockValidation:
    @pytest.fixture(scope="module")
    async def initial_blockchain(self):
        """
        Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
        """
        blocks = bt.get_consecutive_blocks(test_constants, 10, [], 10)
        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        store = await BlockStore.create(connection)
        coin_store = await CoinStore.create(connection)
        b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
        for i in range(1, 9):
            result, removed, error_code = await b.receive_block(blocks[i])
            assert result == ReceiveBlockResult.ADDED_TO_HEAD
        yield (blocks, b)

        await connection.close()

    @pytest.mark.asyncio
    async def test_prev_pointer(self, initial_blockchain):
        blocks, b = initial_blockchain
        block_bad = FullBlock(
            blocks[9].proof_of_space,
            blocks[9].proof_of_time,
            Header(
                HeaderData(
                    blocks[9].header.data.height,
                    bytes([1] * 32),
                    blocks[9].header.data.timestamp,
                    blocks[9].header.data.filter_hash,
                    blocks[9].header.data.proof_of_space_hash,
                    blocks[9].header.data.weight,
                    blocks[9].header.data.total_iters,
                    blocks[9].header.data.additions_root,
                    blocks[9].header.data.removals_root,
                    blocks[9].header.data.coinbase,
                    blocks[9].header.data.coinbase_signature,
                    blocks[9].header.data.fees_coin,
                    blocks[9].header.data.aggregated_signature,
                    blocks[9].header.data.cost,
                    blocks[9].header.data.extension_data,
                    blocks[9].header.data.generator_hash,
                ),
                blocks[9].header.harvester_signature,
            ),
            blocks[9].transactions_generator,
            blocks[9].transactions_filter,
        )
        result, removed, error_code = await b.receive_block(block_bad)
        assert (result) == ReceiveBlockResult.DISCONNECTED_BLOCK
        assert error_code is None

    @pytest.mark.asyncio
    async def test_prev_block(self, initial_blockchain):
        blocks, b = initial_blockchain
        block_bad = blocks[10]
        result, removed, error_code = await b.receive_block(block_bad)
        assert (result) == ReceiveBlockResult.DISCONNECTED_BLOCK
        assert error_code is None

    @pytest.mark.asyncio
    async def test_timestamp(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        new_header_data = HeaderData(
            blocks[9].header.data.height,
            blocks[9].header.data.prev_header_hash,
            blocks[9].header.data.timestamp - 1000,
            blocks[9].header.data.filter_hash,
            blocks[9].header.data.proof_of_space_hash,
            blocks[9].header.data.weight,
            blocks[9].header.data.total_iters,
            blocks[9].header.data.additions_root,
            blocks[9].header.data.removals_root,
            blocks[9].header.data.coinbase,
            blocks[9].header.data.coinbase_signature,
            blocks[9].header.data.fees_coin,
            blocks[9].header.data.aggregated_signature,
            blocks[9].header.data.cost,
            blocks[9].header.data.extension_data,
            blocks[9].header.data.generator_hash,
        )

        block_bad = FullBlock(
            blocks[9].proof_of_space,
            blocks[9].proof_of_time,
            Header(
                new_header_data,
                bt.get_harvester_signature(
                    new_header_data, blocks[9].proof_of_space.plot_pubkey
                ),
            ),
            blocks[9].transactions_generator,
            blocks[9].transactions_filter,
        )
        result, removed, error_code = await b.receive_block(block_bad)
        assert (result) == ReceiveBlockResult.INVALID_BLOCK
        assert error_code == Err.TIMESTAMP_TOO_FAR_IN_PAST

        # Time too far in the future
        new_header_data = HeaderData(
            blocks[9].header.data.height,
            blocks[9].header.data.prev_header_hash,
            uint64(int(time.time() + 3600 * 3)),
            blocks[9].header.data.filter_hash,
            blocks[9].header.data.proof_of_space_hash,
            blocks[9].header.data.weight,
            blocks[9].header.data.total_iters,
            blocks[9].header.data.additions_root,
            blocks[9].header.data.removals_root,
            blocks[9].header.data.coinbase,
            blocks[9].header.data.coinbase_signature,
            blocks[9].header.data.fees_coin,
            blocks[9].header.data.aggregated_signature,
            blocks[9].header.data.cost,
            blocks[9].header.data.extension_data,
            blocks[9].header.data.generator_hash,
        )
        block_bad = FullBlock(
            blocks[9].proof_of_space,
            blocks[9].proof_of_time,
            Header(
                new_header_data,
                bt.get_harvester_signature(
                    new_header_data, blocks[9].proof_of_space.plot_pubkey
                ),
            ),
            blocks[9].transactions_generator,
            blocks[9].transactions_filter,
        )
        result, removed, error_code = await b.receive_block(block_bad)
        assert (result) == ReceiveBlockResult.INVALID_BLOCK
        assert error_code == Err.TIMESTAMP_TOO_FAR_IN_FUTURE

    @pytest.mark.asyncio
    async def test_generator_hash(self, initial_blockchain):
        blocks, b = initial_blockchain
        new_header_data = HeaderData(
            blocks[9].header.data.height,
            blocks[9].header.data.prev_header_hash,
            blocks[9].header.data.timestamp,
            blocks[9].header.data.filter_hash,
            blocks[9].header.data.proof_of_space_hash,
            blocks[9].header.data.weight,
            blocks[9].header.data.total_iters,
            blocks[9].header.data.additions_root,
            blocks[9].header.data.removals_root,
            blocks[9].header.data.coinbase,
            blocks[9].header.data.coinbase_signature,
            blocks[9].header.data.fees_coin,
            blocks[9].header.data.aggregated_signature,
            blocks[9].header.data.cost,
            blocks[9].header.data.extension_data,
            bytes([1] * 32),
        )

        block_bad = FullBlock(
            blocks[9].proof_of_space,
            blocks[9].proof_of_time,
            Header(
                new_header_data,
                bt.get_harvester_signature(
                    new_header_data, blocks[9].proof_of_space.plot_pubkey
                ),
            ),
            blocks[9].transactions_generator,
            blocks[9].transactions_filter,
        )
        result, removed, error_code = await b.receive_block(block_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert error_code == Err.INVALID_TRANSACTIONS_GENERATOR_HASH

    @pytest.mark.asyncio
    async def test_harvester_signature(self, initial_blockchain):
        blocks, b = initial_blockchain
        # Time too far in the past
        block_bad = FullBlock(
            blocks[9].proof_of_space,
            blocks[9].proof_of_time,
            Header(
                blocks[9].header.data,
                PrivateKey.from_seed(b"0").sign_prepend(b"random junk"),
            ),
            blocks[9].transactions_generator,
            blocks[9].transactions_filter,
        )
        result, removed, error_code = await b.receive_block(block_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert error_code == Err.INVALID_HARVESTER_SIGNATURE

    @pytest.mark.asyncio
    async def test_invalid_pos(self, initial_blockchain):
        blocks, b = initial_blockchain

        bad_pos_proof = bytearray([i for i in blocks[9].proof_of_space.proof])
        bad_pos_proof[0] = uint8((bad_pos_proof[0] + 1) % 256)
        bad_pos = ProofOfSpace(
            blocks[9].proof_of_space.challenge_hash,
            blocks[9].proof_of_space.pool_pubkey,
            blocks[9].proof_of_space.plot_pubkey,
            blocks[9].proof_of_space.size,
            bytes(bad_pos_proof),
        )
        new_header_data = HeaderData(
            blocks[9].header.data.height,
            blocks[9].header.data.prev_header_hash,
            blocks[9].header.data.timestamp,
            blocks[9].header.data.filter_hash,
            bad_pos.get_hash(),
            blocks[9].header.data.weight,
            blocks[9].header.data.total_iters,
            blocks[9].header.data.additions_root,
            blocks[9].header.data.removals_root,
            blocks[9].header.data.coinbase,
            blocks[9].header.data.coinbase_signature,
            blocks[9].header.data.fees_coin,
            blocks[9].header.data.aggregated_signature,
            blocks[9].header.data.cost,
            blocks[9].header.data.extension_data,
            blocks[9].header.data.generator_hash,
        )

        # Proof of space invalid
        block_bad = FullBlock(
            bad_pos,
            blocks[9].proof_of_time,
            Header(
                new_header_data,
                bt.get_harvester_signature(
                    new_header_data, blocks[9].proof_of_space.plot_pubkey
                ),
            ),
            blocks[9].transactions_generator,
            blocks[9].transactions_filter,
        )
        result, removed, error_code = await b.receive_block(block_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert error_code == Err.INVALID_POSPACE

    @pytest.mark.asyncio
    async def test_invalid_pos_hash(self, initial_blockchain):
        blocks, b = initial_blockchain

        bad_pos_proof = bytearray([i for i in blocks[9].proof_of_space.proof])
        bad_pos_proof[0] = uint8((bad_pos_proof[0] + 1) % 256)
        bad_pos = ProofOfSpace(
            blocks[9].proof_of_space.challenge_hash,
            blocks[9].proof_of_space.pool_pubkey,
            blocks[9].proof_of_space.plot_pubkey,
            blocks[9].proof_of_space.size,
            bytes(bad_pos_proof),
        )
        new_header_data = HeaderData(
            blocks[9].header.data.height,
            blocks[9].header.data.prev_header_hash,
            blocks[9].header.data.timestamp,
            blocks[9].header.data.filter_hash,
            bad_pos.get_hash(),
            blocks[9].header.data.weight,
            blocks[9].header.data.total_iters,
            blocks[9].header.data.additions_root,
            blocks[9].header.data.removals_root,
            blocks[9].header.data.coinbase,
            blocks[9].header.data.coinbase_signature,
            blocks[9].header.data.fees_coin,
            blocks[9].header.data.aggregated_signature,
            blocks[9].header.data.cost,
            blocks[9].header.data.extension_data,
            blocks[9].header.data.generator_hash,
        )

        # Proof of space has invalid
        block_bad = FullBlock(
            blocks[9].proof_of_space,
            blocks[9].proof_of_time,
            Header(
                new_header_data,
                bt.get_harvester_signature(
                    new_header_data, blocks[9].proof_of_space.plot_pubkey
                ),
            ),
            blocks[9].transactions_generator,
            blocks[9].transactions_filter,
        )
        result, removed, error_code = await b.receive_block(block_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert error_code == Err.INVALID_POSPACE_HASH

    @pytest.mark.asyncio
    async def test_invalid_filter_hash(self, initial_blockchain):
        blocks, b = initial_blockchain

        new_header_data = HeaderData(
            blocks[9].header.data.height,
            blocks[9].header.data.prev_header_hash,
            blocks[9].header.data.timestamp,
            bytes32(bytes([3] * 32)),
            blocks[9].header.data.proof_of_space_hash,
            blocks[9].header.data.weight,
            blocks[9].header.data.total_iters,
            blocks[9].header.data.additions_root,
            blocks[9].header.data.removals_root,
            blocks[9].header.data.coinbase,
            blocks[9].header.data.coinbase_signature,
            blocks[9].header.data.fees_coin,
            blocks[9].header.data.aggregated_signature,
            blocks[9].header.data.cost,
            blocks[9].header.data.extension_data,
            blocks[9].header.data.generator_hash,
        )

        block_bad = FullBlock(
            blocks[9].proof_of_space,
            blocks[9].proof_of_time,
            Header(
                new_header_data,
                bt.get_harvester_signature(
                    new_header_data, blocks[9].proof_of_space.plot_pubkey
                ),
            ),
            blocks[9].transactions_generator,
            blocks[9].transactions_filter,
        )
        result, removed, error_code = await b.receive_block(block_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert error_code == Err.INVALID_TRANSACTIONS_FILTER_HASH

    @pytest.mark.asyncio
    async def test_invalid_coinbase_amount(self, initial_blockchain):
        blocks, b = initial_blockchain

        coinbase_coin, coinbase_signature = create_coinbase_coin_and_signature(
            blocks[9].header.data.height,
            blocks[9].header.data.coinbase.puzzle_hash,
            uint64(9991),
            PrivateKey.from_bytes(
                bytes.fromhex(list(bt.plot_config["plots"].values())[0]["pool_sk"])
            ),
        )
        new_header_data = HeaderData(
            blocks[9].header.data.height,
            blocks[9].header.data.prev_header_hash,
            blocks[9].header.data.timestamp,
            blocks[9].header.data.filter_hash,
            blocks[9].header.data.proof_of_space_hash,
            blocks[9].header.data.weight,
            blocks[9].header.data.total_iters,
            blocks[9].header.data.additions_root,
            blocks[9].header.data.removals_root,
            coinbase_coin,
            coinbase_signature,
            blocks[9].header.data.fees_coin,
            blocks[9].header.data.aggregated_signature,
            blocks[9].header.data.cost,
            blocks[9].header.data.extension_data,
            blocks[9].header.data.generator_hash,
        )

        # Coinbase amount invalid
        block_bad = FullBlock(
            blocks[9].proof_of_space,
            blocks[9].proof_of_time,
            Header(
                new_header_data,
                bt.get_harvester_signature(
                    new_header_data, blocks[9].proof_of_space.plot_pubkey
                ),
            ),
            blocks[9].transactions_generator,
            blocks[9].transactions_filter,
        )
        result, removed, error_code = await b.receive_block(block_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert error_code == Err.INVALID_COINBASE_AMOUNT

    @pytest.mark.asyncio
    async def test_invalid_coinbase_signature(self, initial_blockchain):
        blocks, b = initial_blockchain

        coinbase_coin, coinbase_signature = create_coinbase_coin_and_signature(
            blocks[9].header.data.height,
            blocks[9].header.data.coinbase.puzzle_hash,
            uint64(9991),
            PrivateKey.from_bytes(
                bytes.fromhex(list(bt.plot_config["plots"].values())[0]["pool_sk"])
            ),
        )
        new_header_data = HeaderData(
            blocks[9].header.data.height,
            blocks[9].header.data.prev_header_hash,
            blocks[9].header.data.timestamp,
            blocks[9].header.data.filter_hash,
            blocks[9].header.data.proof_of_space_hash,
            blocks[9].header.data.weight,
            blocks[9].header.data.total_iters,
            blocks[9].header.data.additions_root,
            blocks[9].header.data.removals_root,
            blocks[9].header.data.coinbase,
            coinbase_signature,
            blocks[9].header.data.fees_coin,
            blocks[9].header.data.aggregated_signature,
            blocks[9].header.data.cost,
            blocks[9].header.data.extension_data,
            blocks[9].header.data.generator_hash,
        )

        # Coinbase amount invalid
        block_bad = FullBlock(
            blocks[9].proof_of_space,
            blocks[9].proof_of_time,
            Header(
                new_header_data,
                bt.get_harvester_signature(
                    new_header_data, blocks[9].proof_of_space.plot_pubkey
                ),
            ),
            blocks[9].transactions_generator,
            blocks[9].transactions_filter,
        )
        result, removed, error_code = await b.receive_block(block_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert error_code == Err.INVALID_COINBASE_SIGNATURE

    @pytest.mark.asyncio
    async def test_difficulty_change(self):
        num_blocks = 14
        # Make it 5x faster than target time
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 1)
        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)
        store = await BlockStore.create(connection)
        b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
        for i in range(1, num_blocks):
            result, removed, error_code = await b.receive_block(blocks[i])
            assert result == ReceiveBlockResult.ADDED_TO_HEAD
            assert error_code is None

        diff_12 = b.get_next_difficulty(blocks[11].header)
        diff_13 = b.get_next_difficulty(blocks[12].header)
        diff_14 = b.get_next_difficulty(blocks[13].header)

        assert diff_13 == diff_12
        assert diff_14 > diff_13
        assert (diff_14 / diff_13) <= test_constants["DIFFICULTY_FACTOR"]

        assert (b.get_next_min_iters(blocks[1])) == test_constants["MIN_ITERS_STARTING"]
        assert (b.get_next_min_iters(blocks[12])) == (b.get_next_min_iters(blocks[11]))
        assert (b.get_next_min_iters(blocks[13])) > (b.get_next_min_iters(blocks[12]))
        assert (b.get_next_min_iters(blocks[14])) == (b.get_next_min_iters(blocks[13]))

        await connection.close()
        b.shut_down()


class TestReorgs:
    @pytest.mark.asyncio
    async def test_basic_reorg(self):
        blocks = bt.get_consecutive_blocks(test_constants, 15, [], 9)
        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)
        store = await BlockStore.create(connection)
        b: Blockchain = await Blockchain.create(coin_store, store, test_constants)

        for i in range(1, len(blocks)):
            await b.receive_block(blocks[i])
        assert b.get_current_tips()[0].height == 15

        blocks_reorg_chain = bt.get_consecutive_blocks(
            test_constants, 7, blocks[:10], 9, b"2"
        )
        for i in range(1, len(blocks_reorg_chain)):
            reorg_block = blocks_reorg_chain[i]
            result, removed, error_code = await b.receive_block(reorg_block)
            if reorg_block.height < 10:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height < 14:
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
            elif reorg_block.height >= 15:
                assert result == ReceiveBlockResult.ADDED_TO_HEAD
            assert error_code is None
        assert b.get_current_tips()[0].height == 16

        await connection.close()
        b.shut_down()

    @pytest.mark.asyncio
    async def test_reorg_from_genesis(self):
        blocks = bt.get_consecutive_blocks(test_constants, 20, [], 9, b"0")
        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)
        store = await BlockStore.create(connection)
        b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
        for i in range(1, len(blocks)):
            await b.receive_block(blocks[i])
        assert b.get_current_tips()[0].height == 20

        # Reorg from genesis
        blocks_reorg_chain = bt.get_consecutive_blocks(
            test_constants, 21, [blocks[0]], 9, b"3"
        )
        for i in range(1, len(blocks_reorg_chain)):
            reorg_block = blocks_reorg_chain[i]
            result, removed, error_code = await b.receive_block(reorg_block)
            if reorg_block.height == 0:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height < 19:
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
            else:
                assert result == ReceiveBlockResult.ADDED_TO_HEAD
        assert b.get_current_tips()[0].height == 21

        # Reorg back to original branch
        blocks_reorg_chain_2 = bt.get_consecutive_blocks(
            test_constants, 3, blocks[:-1], 9, b"4"
        )
        result, _, error_code = await b.receive_block(blocks_reorg_chain_2[20])
        assert result == ReceiveBlockResult.ADDED_AS_ORPHAN

        result, _, error_code = await b.receive_block(blocks_reorg_chain_2[21])
        assert result == ReceiveBlockResult.ADDED_TO_HEAD

        result, _, error_code = await b.receive_block(blocks_reorg_chain_2[22])
        assert result == ReceiveBlockResult.ADDED_TO_HEAD

        await connection.close()
        b.shut_down()

    @pytest.mark.asyncio
    async def test_lca(self):
        blocks = bt.get_consecutive_blocks(test_constants, 5, [], 9, b"0")
        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)
        store = await BlockStore.create(connection)
        b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
        for i in range(1, len(blocks)):
            await b.receive_block(blocks[i])

        assert b.lca_block.header_hash == blocks[3].header_hash
        block_5_2 = bt.get_consecutive_blocks(test_constants, 1, blocks[:5], 9, b"1")
        block_5_3 = bt.get_consecutive_blocks(test_constants, 1, blocks[:5], 9, b"2")

        await b.receive_block(block_5_2[5])
        assert b.lca_block.header_hash == blocks[4].header_hash
        await b.receive_block(block_5_3[5])
        assert b.lca_block.header_hash == blocks[4].header_hash

        reorg = bt.get_consecutive_blocks(test_constants, 6, [], 9, b"3")
        for i in range(1, len(reorg)):
            await b.receive_block(reorg[i])
        assert b.lca_block.header_hash == blocks[0].header_hash

        await connection.close()
        b.shut_down()

    @pytest.mark.asyncio
    async def test_find_fork_point(self):
        blocks = bt.get_consecutive_blocks(test_constants, 10, [], 9, b"7")
        blocks_2 = bt.get_consecutive_blocks(test_constants, 6, blocks[:5], 9, b"8")
        blocks_3 = bt.get_consecutive_blocks(test_constants, 8, blocks[:3], 9, b"9")

        blocks_reorg = bt.get_consecutive_blocks(test_constants, 3, blocks[:9], 9, b"9")

        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)
        store = await BlockStore.create(connection)
        b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
        for i in range(1, len(blocks)):
            await b.receive_block(blocks[i])

        for i in range(1, len(blocks_2)):
            await b.receive_block(blocks_2[i])

        assert (
            find_fork_point_in_chain(b.headers, blocks[10].header, blocks_2[10].header)
            == 4
        )

        for i in range(1, len(blocks_3)):
            await b.receive_block(blocks_3[i])

        assert (
            find_fork_point_in_chain(b.headers, blocks[10].header, blocks_3[10].header)
            == 2
        )

        assert b.lca_block.data == blocks[2].header.data

        for i in range(1, len(blocks_reorg)):
            await b.receive_block(blocks_reorg[i])

        assert (
            find_fork_point_in_chain(
                b.headers, blocks[10].header, blocks_reorg[10].header
            )
            == 8
        )
        assert (
            find_fork_point_in_chain(
                b.headers, blocks_2[10].header, blocks_reorg[10].header
            )
            == 4
        )
        assert b.lca_block.data == blocks[4].header.data
        await connection.close()
        b.shut_down()

    @pytest.mark.asyncio
    async def test_get_header_hashes(self):
        blocks = bt.get_consecutive_blocks(test_constants, 5, [], 9, b"0")
        db_path = Path("blockchain_test.db")
        if db_path.exists():
            db_path.unlink()
        connection = await aiosqlite.connect(db_path)
        coin_store = await CoinStore.create(connection)
        store = await BlockStore.create(connection)
        b: Blockchain = await Blockchain.create(coin_store, store, test_constants)

        for i in range(1, len(blocks)):
            await b.receive_block(blocks[i])
        header_hashes = b.get_header_hashes(blocks[-1].header_hash)
        assert len(header_hashes) == 6
        assert header_hashes == [block.header_hash for block in blocks]

        await connection.close()
        b.shut_down()
