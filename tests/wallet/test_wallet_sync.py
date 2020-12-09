import asyncio

import pytest

from src.types.peer_info import PeerInfo
from src.protocols import full_node_protocol
from src.util.ints import uint16, uint64, uint32
from tests.setup_nodes import setup_node_and_wallet, test_constants, bt
from src.types.spend_bundle import SpendBundle
from src.full_node.bundle_tools import best_solution_program
from src.types.coin import Coin
from src.consensus.coinbase import create_coinbase_coin
from tests.time_out_assert import time_out_assert


def wallet_height_at_least(wallet_node, h):
    if wallet_node.wallet_state_manager.block_records[wallet_node.wallet_state_manager.lca].height >= h:
        return True
    return False


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletSync:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        constants = test_constants.replace(COINBASE_FREEZE_PERIOD=0)
        async for _ in setup_node_and_wallet(constants):
            yield _

    @pytest.fixture(scope="function")
    async def wallet_node_starting_height(self):
        async for _ in setup_node_and_wallet(test_constants, starting_height=100):
            yield _

    @pytest.mark.asyncio
    async def test_basic_sync_wallet(self, wallet_node):
        num_blocks = 300  # This must be greater than the short_sync in wallet_node
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [])
        full_node_api, wallet_node, full_node_server, wallet_server = wallet_node

        for i in range(1, len(blocks)):
            await full_node_api.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(blocks[i]))

        await wallet_server.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1.
        await time_out_assert(200, wallet_height_at_least, True, wallet_node, num_blocks - 6)

        # Tests a reorg with the wallet
        blocks_reorg = bt.get_consecutive_blocks(test_constants, 15, blocks[:-5])
        for i in range(1, len(blocks_reorg)):
            await full_node_api.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(blocks_reorg[i]))

        await time_out_assert(200, wallet_height_at_least, True, wallet_node, 33)

    @pytest.mark.asyncio
    async def test_fast_sync_wallet(self, wallet_node_starting_height):
        num_blocks = 25  # This must be greater than the short_sync in wallet_node
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [])
        full_node_1, wallet_node, server_1, server_2 = wallet_node_starting_height

        for i in range(1, len(blocks)):
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(blocks[i]))

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        await time_out_assert(60, wallet_height_at_least, True, wallet_node, num_blocks - 6)

    @pytest.mark.asyncio
    async def test_short_sync_wallet(self, wallet_node):
        num_blocks = 5  # This must be lower than the short_sync in wallet_node
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)
        full_node_1, wallet_node, server_1, server_2 = wallet_node

        for i in range(1, len(blocks)):
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(blocks[i]))

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await time_out_assert(60, wallet_height_at_least, True, wallet_node, 3)

    @pytest.mark.asyncio
    async def test_short_sync_with_transactions_wallet(self, wallet_node):
        BURN_PUZZLE_HASH_1 = b"0" * 32
        BURN_PUZZLE_HASH_2 = b"1" * 32
        full_node_1, wallet_node, server_1, server_2 = wallet_node
        wallet_a = wallet_node.wallet_state_manager.main_wallet
        coinbase_puzzlehash = await wallet_a.get_new_puzzlehash()
        coinbase_puzzlehash_rest = BURN_PUZZLE_HASH_1
        puzzle_hashes = [await wallet_a.get_new_puzzlehash() for _ in range(10)]
        puzzle_hashes.append(BURN_PUZZLE_HASH_2)

        blocks = bt.get_consecutive_blocks(test_constants, 3, [], 10, b"", coinbase_puzzlehash)
        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await time_out_assert(60, wallet_height_at_least, True, wallet_node, 1)

        await server_2.close_all_connections()

        dic_h = {}
        prev_coin = blocks[1].get_coinbase()
        for i in range(11):
            pk, sk = await wallet_a.wallet_state_manager.get_keys(prev_coin.puzzle_hash)
            transaction_unsigned = await wallet_a.generate_unsigned_transaction(
                1000, puzzle_hashes[i], coins=[prev_coin]
            )
            spend_bundle = await wallet_a.sign_transaction(transaction_unsigned)
            block_spendbundle = SpendBundle.aggregate([spend_bundle])
            program = best_solution_program(block_spendbundle)
            aggsig = block_spendbundle.aggregated_signature
            prev_coin = Coin(prev_coin.name(), puzzle_hashes[i], uint64(1000))
            dic_h[i + 4] = (program, aggsig)

        blocks = bt.get_consecutive_blocks(test_constants, 13, blocks, 10, b"", coinbase_puzzlehash_rest, dic_h)
        # Move chain to height 16, with consecutive transactions in blocks 4 to 14
        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # Do a short sync from 0 to 14
        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await time_out_assert(60, wallet_height_at_least, True, wallet_node, 14)

        await server_2.close_all_connections()

        # 3 block rewards and 3 fees - 1000 coins spent
        assert (
            await wallet_a.get_confirmed_balance()
            == (blocks[1].get_coinbase().amount * 3) + (blocks[1].get_fees_coin().amount * 3) - 1000
        )
        # All of our coins are spent and puzzle hashes present
        for puzzle_hash in puzzle_hashes[:-1]:
            records = await wallet_node.wallet_state_manager.wallet_store.get_coin_records_by_puzzle_hash(puzzle_hash)
            assert len(records) == 1
            assert records[0].spent and not records[0].coinbase

        # Then do the same but in a reorg chain
        dic_h = {}
        prev_coin = blocks[1].get_coinbase()
        for i in range(11):
            pk, sk = await wallet_a.wallet_state_manager.get_keys(prev_coin.puzzle_hash)
            transaction_unsigned = await wallet_a.generate_unsigned_transaction(
                1000,
                puzzle_hashes[i],
                coins=[prev_coin],
            )
            spend_bundle = await wallet_a.sign_transaction(transaction_unsigned)
            block_spendbundle = SpendBundle.aggregate([spend_bundle])
            program = best_solution_program(block_spendbundle)
            aggsig = block_spendbundle.aggregated_signature
            prev_coin = Coin(prev_coin.name(), puzzle_hashes[i], uint64(1000))
            dic_h[i + 4] = (program, aggsig)

        blocks = bt.get_consecutive_blocks(
            test_constants,
            31,
            blocks[:4],
            10,
            b"this is a reorg",
            coinbase_puzzlehash_rest,
            dic_h,
        )

        # Move chain to height 34, with consecutive transactions in blocks 4 to 14
        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # Do a sync from 0 to 22
        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        await time_out_assert(60, wallet_height_at_least, True, wallet_node, 28)
        await server_2.close_all_connections()

        # 3 block rewards and 3 fees - 1000 coins spent
        assert (
            await wallet_a.get_confirmed_balance()
            == (blocks[1].get_coinbase().amount * 3) + (blocks[1].get_fees_coin().amount * 3) - 1000
        )
        # All of our coins are spent and puzzle hashes present
        for puzzle_hash in puzzle_hashes[:-1]:
            records = await wallet_node.wallet_state_manager.wallet_store.get_coin_records_by_puzzle_hash(puzzle_hash)
            assert len(records) == 1
            assert records[0].spent and not records[0].coinbase

        # Test spending the rewards earned in reorg
        new_coinbase_puzzlehash = await wallet_a.get_new_puzzlehash()
        another_puzzlehash = await wallet_a.get_new_puzzlehash()

        dic_h = {}
        pk, sk = await wallet_a.wallet_state_manager.get_keys(new_coinbase_puzzlehash)
        coinbase_coin = create_coinbase_coin(uint32(25), new_coinbase_puzzlehash, uint64(14000000000000))
        transaction_unsigned = await wallet_a.generate_unsigned_transaction(
            7000000000000,
            another_puzzlehash,
            coins=[coinbase_coin],
        )
        spend_bundle = await wallet_a.sign_transaction(transaction_unsigned)
        block_spendbundle = SpendBundle.aggregate([spend_bundle])
        program = best_solution_program(block_spendbundle)
        aggsig = block_spendbundle.aggregated_signature
        dic_h[26] = (program, aggsig)

        # Farm a block (25) to ourselves
        blocks = bt.get_consecutive_blocks(
            test_constants,
            1,
            blocks[:25],
            10,
            b"this is yet another reorg",
            new_coinbase_puzzlehash,
        )

        # Brings height up to 40, with block 31 having half our reward spent to us
        blocks = bt.get_consecutive_blocks(
            test_constants,
            15,
            blocks,
            10,
            b"this is yet another reorg more blocks",
            coinbase_puzzlehash_rest,
            dic_h,
        )
        for block in blocks:
            await full_node_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await time_out_assert(60, wallet_height_at_least, True, wallet_node, 38)

        # 4 block rewards and 4 fees - 1000 coins spent
        assert (
            await wallet_a.get_confirmed_balance()
            == (blocks[1].get_coinbase().amount * 4) + (blocks[1].get_fees_coin().amount * 4) - 1000
        )
        records = await wallet_node.wallet_state_manager.wallet_store.get_coin_records_by_puzzle_hash(
            new_coinbase_puzzlehash
        )
        # Fee and coinbase
        assert len(records) == 2
        print(records)
        assert records[0].spent != records[1].spent
        assert records[0].coinbase == records[1].coinbase
        records = await wallet_node.wallet_state_manager.wallet_store.get_coin_records_by_puzzle_hash(
            another_puzzlehash
        )
        assert len(records) == 1
        assert not records[0].spent
        assert not records[0].coinbase
