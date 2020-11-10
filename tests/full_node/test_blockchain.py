import asyncio
from pathlib import Path

import aiosqlite
import pytest

from src.full_node.block_store import BlockStore
from src.full_node.blockchain import Blockchain, ReceiveBlockResult
from src.full_node.coin_store import CoinStore
from src.types.classgroup import ClassgroupElement
from src.util.block_tools import get_vdf_info_and_proof
from src.util.errors import Err
from src.util.ints import uint64
from tests.recursive_replace import recursive_replace
from tests.setup_nodes import test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="function")
async def empty_blockchain():
    """
    Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
    """
    db_path = Path("blockchain_test.db")
    if db_path.exists():
        db_path.unlink()
    connection = await aiosqlite.connect(db_path)
    coin_store = await CoinStore.create(connection)
    store = await BlockStore.create(connection)
    bc1 = await Blockchain.create(coin_store, store, test_constants)
    assert bc1.get_peak() is None

    yield bc1

    await connection.close()
    bc1.shut_down()


class TestGenesisBlock:
    @pytest.mark.asyncio
    async def test_block_tools_proofs(self):
        vdf, proof = get_vdf_info_and_proof(
            test_constants, ClassgroupElement.get_default_element(), test_constants.FIRST_CC_CHALLENGE, uint64(231)
        )
        if proof.is_valid(test_constants, vdf) is False:
            raise Exception("invalid proof")

    @pytest.mark.asyncio
    async def test_non_overflow_genesis(self, empty_blockchain):
        assert empty_blockchain.get_peak() is None
        genesis = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK
        assert empty_blockchain.get_peak().height == 0

    @pytest.mark.asyncio
    async def test_overflow_genesis(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(test_constants, 1, force_overflow=True)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_genesis_empty_slots(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False, force_empty_slots=9)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_overflow_genesis_empty_slots(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(test_constants, 1, force_overflow=True, force_empty_slots=10)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_genesis_validate_1(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False)[0]
        bad_prev = bytes([1] * 32)
        genesis = recursive_replace(genesis, "foliage_sub_block.prev_sub_block_hash", bad_prev)
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err == Err.INVALID_PREV_BLOCK_HASH


class TestAddingMoreBlocks:
    @pytest.mark.asyncio
    async def test_non_genesis(self, empty_blockchain):
        blocks = bt.get_consecutive_blocks(test_constants, 200, force_overflow=False, force_empty_slots=0)
        for block in blocks:
            result, err, _ = await empty_blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK
            print(
                f"Added block {block.height} total iters {block.total_iters} new slot? {len(block.finished_sub_slots)}"
            )
        assert empty_blockchain.get_peak().height == len(blocks) - 1


#
# # class TestBlockValidation:
#     @pytest.fixture(scope="module")
#     async def initial_blockchain(self):
#         """
#         Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
#         """
#         blocks = bt.get_consecutive_blocks(test_constants, 10, [], 10)
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         store = await BlockStore.create(connection)
#         coin_store = await CoinStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#         for i in range(1, 9):
#             result, removed, error_code = await b.receive_block(blocks[i])
#             assert result == ReceiveBlockResult.NEW_TIP
#         yield (blocks, b)
#
#         await connection.close()
#
#     @pytest.mark.asyncio
#     async def test_prev_pointer(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 HeaderData(
#                     blocks[9].header.data.height,
#                     bytes([1] * 32),
#                     blocks[9].header.data.timestamp,
#                     blocks[9].header.data.filter_hash,
#                     blocks[9].header.data.proof_of_space_hash,
#                     blocks[9].header.data.weight,
#                     blocks[9].header.data.total_iters,
#                     blocks[9].header.data.additions_root,
#                     blocks[9].header.data.removals_root,
#                     blocks[9].header.data.farmer_rewards_puzzle_hash,
#                     blocks[9].header.data.total_transaction_fees,
#                     blocks[9].header.data.pool_target,
#                     blocks[9].header.data.aggregated_signature,
#                     blocks[9].header.data.cost,
#                     blocks[9].header.data.extension_data,
#                     blocks[9].header.data.generator_hash,
#                 ),
#                 blocks[9].header.plot_signature,
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert (result) == ReceiveBlockResult.DISCONNECTED_BLOCK
#         assert error_code is None
#
#     @pytest.mark.asyncio
#     async def test_prev_block(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         block_bad = blocks[10]
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert (result) == ReceiveBlockResult.DISCONNECTED_BLOCK
#         assert error_code is None
#
#     @pytest.mark.asyncio
#     async def test_timestamp(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         # Time too far in the past
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp - 1000,
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert (result) == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.TIMESTAMP_TOO_FAR_IN_PAST
#
#         # Time too far in the future
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             uint64(int(time.time() + 3600 * 3)),
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert (result) == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.TIMESTAMP_TOO_FAR_IN_FUTURE
#
#     @pytest.mark.asyncio
#     async def test_generator_hash(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             bytes([1] * 32),
#         )
#
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_TRANSACTIONS_GENERATOR_HASH
#
#     @pytest.mark.asyncio
#     async def test_plot_signature(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         # Time too far in the past
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 blocks[9].header.data,
#                 AugSchemeMPL.sign(AugSchemeMPL.key_gen(bytes([5] * 32)), token_bytes(32)),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_PLOT_SIGNATURE
#
#     @pytest.mark.asyncio
#     async def test_invalid_pos(self, initial_blockchain):
#         blocks, b = initial_blockchain
#
#         bad_pos_proof = bytearray([i for i in blocks[9].proof_of_space.proof])
#         bad_pos_proof[0] = uint8((bad_pos_proof[0] + 1) % 256)
#         bad_pos = ProofOfSpace(
#             blocks[9].proof_of_space.challenge_hash,
#             blocks[9].proof_of_space.pool_public_key,
#             blocks[9].proof_of_space.plot_public_key,
#             blocks[9].proof_of_space.size,
#             bytes(bad_pos_proof),
#         )
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             bad_pos.get_hash(),
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         # Proof of space invalid
#         block_bad = FullBlock(
#             bad_pos,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_POSPACE
#
#     @pytest.mark.asyncio
#     async def test_invalid_pos_hash(self, initial_blockchain):
#         blocks, b = initial_blockchain
#
#         bad_pos_proof = bytearray([i for i in blocks[9].proof_of_space.proof])
#         bad_pos_proof[0] = uint8((bad_pos_proof[0] + 1) % 256)
#         bad_pos = ProofOfSpace(
#             blocks[9].proof_of_space.challenge_hash,
#             blocks[9].proof_of_space.pool_public_key,
#             blocks[9].proof_of_space.plot_public_key,
#             blocks[9].proof_of_space.size,
#             bytes(bad_pos_proof),
#         )
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             bad_pos.get_hash(),
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         # Proof of space has invalid
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_POSPACE_HASH
#
#     @pytest.mark.asyncio
#     async def test_invalid_filter_hash(self, initial_blockchain):
#         blocks, b = initial_blockchain
#
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             bytes32(bytes([3] * 32)),
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_TRANSACTIONS_FILTER_HASH
#
#     @pytest.mark.asyncio
#     async def test_invalid_max_height(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         print(blocks[9].header)
#         pool_target = PoolTarget(blocks[9].header.data.pool_target.puzzle_hash, uint32(8))
#         agg_sig = bt.get_pool_key_signature(pool_target, blocks[9].proof_of_space.pool_public_key)
#         assert agg_sig is not None
#
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             pool_target,
#             agg_sig,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_POOL_TARGET
#
#     @pytest.mark.asyncio
#     async def test_invalid_pool_sig(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         pool_target = PoolTarget(blocks[9].header.data.pool_target.puzzle_hash, uint32(10))
#         agg_sig = bt.get_pool_key_signature(pool_target, blocks[9].proof_of_space.pool_public_key)
#         assert agg_sig is not None
#
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             agg_sig,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.BAD_AGGREGATE_SIGNATURE
#
#     @pytest.mark.asyncio
#     async def test_invalid_fees_amount(self, initial_blockchain):
#         blocks, b = initial_blockchain
#
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees + 1,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         # Coinbase amount invalid
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_BLOCK_FEE_AMOUNT
#
#     @pytest.mark.asyncio
#     async def test_difficulty_change(self):
#         num_blocks = 10
#         # Make it much faster than target time, 1 second instead of 10 seconds, so difficulty goes up
#         blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 1)
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#         for i in range(1, num_blocks):
#             result, removed, error_code = await b.receive_block(blocks[i])
#             assert result == ReceiveBlockResult.NEW_TIP
#             assert error_code is None
#
#         diff_6 = b.get_next_difficulty(blocks[5].header)
#         diff_7 = b.get_next_difficulty(blocks[6].header)
#         diff_8 = b.get_next_difficulty(blocks[7].header)
#         # diff_9 = b.get_next_difficulty(blocks[8].header)
#
#         assert diff_6 == diff_7
#         assert diff_8 > diff_7
#         assert (diff_8 / diff_7) <= test_constants.DIFFICULTY_FACTOR
#         assert (b.get_next_min_iters(blocks[1])) == test_constants.MIN_ITERS_STARTING
#         assert (b.get_next_min_iters(blocks[6])) == (b.get_next_min_iters(blocks[5]))
#         assert (b.get_next_min_iters(blocks[7])) > (b.get_next_min_iters(blocks[6]))
#         assert (b.get_next_min_iters(blocks[8])) == (b.get_next_min_iters(blocks[7]))
#
#         await connection.close()
#         b.shut_down()
#
#
# class TestReorgs:
#     @pytest.mark.asyncio
#     async def test_basic_reorg(self):
#         blocks = bt.get_consecutive_blocks(test_constants, 15, [], 9)
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#
#         for i in range(1, len(blocks)):
#             await b.receive_block(blocks[i])
#         assert b.get_current_tips()[0].height == 15
#
#         blocks_reorg_chain = bt.get_consecutive_blocks(test_constants, 7, blocks[:10], 9, b"2")
#         for i in range(1, len(blocks_reorg_chain)):
#             reorg_block = blocks_reorg_chain[i]
#             result, removed, error_code = await b.receive_block(reorg_block)
#             if reorg_block.height < 10:
#                 assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
#             elif reorg_block.height < 14:
#                 assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
#             elif reorg_block.height >= 15:
#                 assert result == ReceiveBlockResult.NEW_TIP
#             assert error_code is None
#         assert b.get_current_tips()[0].height == 16
#
#         await connection.close()
#         b.shut_down()
#
#     @pytest.mark.asyncio
#     async def test_reorg_from_genesis(self):
#         blocks = bt.get_consecutive_blocks(test_constants, 20, [], 9, b"0")
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#         for i in range(1, len(blocks)):
#             await b.receive_block(blocks[i])
#         assert b.get_current_tips()[0].height == 20
#
#         # Reorg from genesis
#         blocks_reorg_chain = bt.get_consecutive_blocks(test_constants, 21, [blocks[0]], 9, b"3")
#         for i in range(1, len(blocks_reorg_chain)):
#             reorg_block = blocks_reorg_chain[i]
#             result, removed, error_code = await b.receive_block(reorg_block)
#             if reorg_block.height == 0:
#                 assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
#             elif reorg_block.height < 19:
#                 assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
#             else:
#                 assert result == ReceiveBlockResult.NEW_TIP
#         assert b.get_current_tips()[0].height == 21
#
#         # Reorg back to original branch
#         blocks_reorg_chain_2 = bt.get_consecutive_blocks(test_constants, 3, blocks[:-1], 9, b"4")
#         result, _, error_code = await b.receive_block(blocks_reorg_chain_2[20])
#         assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
#
#         result, _, error_code = await b.receive_block(blocks_reorg_chain_2[21])
#         assert result == ReceiveBlockResult.NEW_TIP
#
#         result, _, error_code = await b.receive_block(blocks_reorg_chain_2[22])
#         assert result == ReceiveBlockResult.NEW_TIP
#
#         await connection.close()
#         b.shut_down()
#
#     @pytest.mark.asyncio
#     async def test_lca(self):
#         blocks = bt.get_consecutive_blocks(test_constants, 5, [], 9, b"0")
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#         for i in range(1, len(blocks)):
#             await b.receive_block(blocks[i])
#
#         assert b.lca_block.header_hash == blocks[3].header_hash
#         block_5_2 = bt.get_consecutive_blocks(test_constants, 1, blocks[:5], 9, b"1")
#         block_5_3 = bt.get_consecutive_blocks(test_constants, 1, blocks[:5], 9, b"2")
#
#         await b.receive_block(block_5_2[5])
#         assert b.lca_block.header_hash == blocks[4].header_hash
#         await b.receive_block(block_5_3[5])
#         assert b.lca_block.header_hash == blocks[4].header_hash
#
#         reorg = bt.get_consecutive_blocks(test_constants, 6, [], 9, b"3")
#         for i in range(1, len(reorg)):
#             await b.receive_block(reorg[i])
#         assert b.lca_block.header_hash == blocks[0].header_hash
#
#         await connection.close()
#         b.shut_down()
#
#     @pytest.mark.asyncio
#     async def test_find_fork_point(self):
#         blocks = bt.get_consecutive_blocks(test_constants, 10, [], 9, b"7")
#         blocks_2 = bt.get_consecutive_blocks(test_constants, 6, blocks[:5], 9, b"8")
#         blocks_3 = bt.get_consecutive_blocks(test_constants, 8, blocks[:3], 9, b"9")
#
#         blocks_reorg = bt.get_consecutive_blocks(test_constants, 3, blocks[:9], 9, b"9")
#
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#         for i in range(1, len(blocks)):
#             await b.receive_block(blocks[i])
#
#         for i in range(1, len(blocks_2)):
#             await b.receive_block(blocks_2[i])
#
#         assert find_fork_point_in_chain(b.headers, blocks[10].header, blocks_2[10].header) == 4
#
#         for i in range(1, len(blocks_3)):
#             await b.receive_block(blocks_3[i])
#
#         assert find_fork_point_in_chain(b.headers, blocks[10].header, blocks_3[10].header) == 2
#
#         assert b.lca_block.data == blocks[2].header.data
#
#         for i in range(1, len(blocks_reorg)):
#             await b.receive_block(blocks_reorg[i])
#
#         assert find_fork_point_in_chain(b.headers, blocks[10].header, blocks_reorg[10].header) == 8
#         assert find_fork_point_in_chain(b.headers, blocks_2[10].header, blocks_reorg[10].header) == 4
#         assert b.lca_block.data == blocks[4].header.data
#         await connection.close()
#         b.shut_down()
#
#     @pytest.mark.asyncio
#     async def test_get_header_hashes(self):
#         blocks = bt.get_consecutive_blocks(test_constants, 5, [], 9, b"0")
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#
#         for i in range(1, len(blocks)):
#             await b.receive_block(blocks[i])
#         header_hashes = b.get_header_hashes(blocks[-1].header_hash)
#         assert len(header_hashes) == 6
#         assert header_hashes == [block.header_hash for block in blocks]
#
#         await connection.close()
#         b.shut_down()
