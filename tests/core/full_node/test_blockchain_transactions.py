import asyncio
import pytest

from src.consensus.blockchain import ReceiveBlockResult
from src.protocols import full_node_protocol
from src.types.condition_opcodes import ConditionOpcode
from src.types.condition_var_pair import ConditionVarPair
from src.types.spend_bundle import SpendBundle
from src.util.errors import Err, ConsensusError
from tests.core.full_node.test_full_node import connect_and_get_peer
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from src.util.wallet_tools import WalletTool

BURN_PUZZLE_HASH = b"0" * 32

WALLET_A = WalletTool()
WALLET_A_PUZZLE_HASHES = [WALLET_A.get_new_puzzlehash() for _ in range(5)]


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestBlockchainTransactions:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes(test_constants):
            yield _

    @pytest.mark.asyncio
    async def test_basic_blockchain_tx(self, two_nodes):
        num_blocks = 10
        wallet_a = WALLET_A
        coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
        receiver_puzzlehash = BURN_PUZZLE_HASH

        blocks = bt.get_consecutive_blocks(
            num_blocks, farmer_reward_puzzle_hash=coinbase_puzzlehash, guarantee_block=True
        )
        full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2)
        full_node_1 = full_node_api_1.full_node

        for block in blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block), None)

        spend_block = blocks[1]
        spend_coin = None
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                spend_coin = coin

        spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, spend_coin)

        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle)
        await full_node_api_1.respond_transaction(tx, peer)

        sb = full_node_1.mempool_manager.get_spendbundle(spend_bundle.name())
        assert sb is spend_bundle

        last_block = blocks[-1]
        next_spendbundle = await full_node_1.mempool_manager.create_bundle_from_mempool(last_block.header_hash)
        assert next_spendbundle is not None

        new_blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=next_spendbundle,
            guarantee_block=True,
        )

        next_block = new_blocks[-1]
        await full_node_1.respond_sub_block(full_node_protocol.RespondSubBlock(next_block))

        assert next_block.header_hash == full_node_1.blockchain.get_peak().header_hash

        added_coins = next_spendbundle.additions()

        # Two coins are added, main spend and change
        assert len(added_coins) == 2
        for coin in added_coins:
            unspent = await full_node_1.coin_store.get_coin_record(coin.name())
            assert unspent is not None
            assert not unspent.spent
            assert not unspent.coinbase

    @pytest.mark.asyncio
    async def test_validate_blockchain_with_double_spend(self, two_nodes):
        num_blocks = 5
        wallet_a = WALLET_A
        coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
        receiver_puzzlehash = BURN_PUZZLE_HASH

        blocks = bt.get_consecutive_blocks(
            num_blocks, farmer_reward_puzzle_hash=coinbase_puzzlehash, guarantee_block=True
        )
        full_node_api_1, full_node_api_3, server_1, server_2 = two_nodes
        full_node_1 = full_node_api_1.full_node

        for block in blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        spend_block = blocks[1]
        spend_coin = None
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                spend_coin = coin

        spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, spend_coin)
        spend_bundle_double = wallet_a.generate_signed_transaction(1001, receiver_puzzlehash, spend_coin)

        block_spendbundle = SpendBundle.aggregate([spend_bundle, spend_bundle_double])

        new_blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=block_spendbundle,
            guarantee_block=True,
        )

        next_block = new_blocks[-1]
        res, err, _ = await full_node_1.blockchain.receive_block(next_block)
        assert res == ReceiveBlockResult.INVALID_BLOCK
        assert err == Err.DOUBLE_SPEND

    @pytest.mark.asyncio
    async def test_validate_blockchain_duplicate_output(self, two_nodes):
        num_blocks = 3
        wallet_a = WALLET_A
        coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
        receiver_puzzlehash = BURN_PUZZLE_HASH

        blocks = bt.get_consecutive_blocks(
            num_blocks, farmer_reward_puzzle_hash=coinbase_puzzlehash, guarantee_block=True
        )
        full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes
        full_node_1 = full_node_api_1.full_node

        for block in blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        spend_block = blocks[1]

        spend_coin = None
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                spend_coin = coin

        spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, spend_coin)
        spend_bundle_double = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, spend_coin)

        block_spendbundle = SpendBundle.aggregate([spend_bundle, spend_bundle_double])

        new_blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=block_spendbundle,
            guarantee_block=True,
        )

        next_block = new_blocks[-1]
        res, err, _ = await full_node_1.blockchain.receive_block(next_block)
        assert res == ReceiveBlockResult.INVALID_BLOCK
        assert err == Err.DUPLICATE_OUTPUT

    @pytest.mark.asyncio
    async def test_validate_blockchain_with_reorg_double_spend(self, two_nodes):
        num_blocks = 10
        wallet_a = WALLET_A
        coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
        receiver_puzzlehash = BURN_PUZZLE_HASH

        blocks = bt.get_consecutive_blocks(
            num_blocks, farmer_reward_puzzle_hash=coinbase_puzzlehash, guarantee_block=True
        )
        full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes

        for block in blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        spend_block = blocks[1]

        spend_coin = None
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                spend_coin = coin

        spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, spend_coin)

        blocks_spend = bt.get_consecutive_blocks(
            1, farmer_reward_puzzle_hash=coinbase_puzzlehash, guarantee_block=True, transaction_data=spend_bundle
        )
        # Move chain to height 10, with a spend at height 10
        for block in blocks_spend:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # Reorg at height 5, add up to and including height 12
        new_blocks = bt.get_consecutive_blocks(
            7,
            blocks[:6],
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            guarantee_block=True,
            seed=b"another seed",
        )

        for block in new_blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # Spend the same coin in the new reorg chain at height 13
        new_blocks = bt.get_consecutive_blocks(
            1,
            new_blocks,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            guarantee_block=True,
            transaction_data=spend_bundle,
        )

        res, err, _ = await full_node_api_1.full_node.blockchain.receive_block(new_blocks[-1])
        assert err is None
        assert res == ReceiveBlockResult.NEW_PEAK

        # But can't spend it twice
        new_blocks_double = bt.get_consecutive_blocks(
            1,
            new_blocks,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            guarantee_block=True,
            transaction_data=spend_bundle,
        )

        res, err, _ = await full_node_api_1.full_node.blockchain.receive_block(new_blocks_double[-1])
        assert err is Err.DOUBLE_SPEND
        assert res == ReceiveBlockResult.INVALID_BLOCK

        # Now test Reorg at block 5, same spend at block height 12
        new_blocks_reorg = bt.get_consecutive_blocks(
            1,
            new_blocks[:12],
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            guarantee_block=True,
            transaction_data=spend_bundle,
            seed=b"spend at 12 is ok",
        )
        for block in new_blocks_reorg:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # Spend at height 13 is also OK (same height)
        new_blocks_reorg = bt.get_consecutive_blocks(
            1,
            new_blocks[:13],
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            guarantee_block=True,
            transaction_data=spend_bundle,
            seed=b"spend at 13 is ok",
        )
        for block in new_blocks_reorg:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # Spend at height 14 is not OK (already spend)
        new_blocks_reorg = bt.get_consecutive_blocks(
            1,
            new_blocks[:14],
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            guarantee_block=True,
            transaction_data=spend_bundle,
            seed=b"spend at 14 is double spend",
        )
        with pytest.raises(ConsensusError):
            for block in new_blocks_reorg:
                await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

    @pytest.mark.asyncio
    async def test_validate_blockchain_spend_reorg_coin(self, two_nodes):
        num_blocks = 10
        wallet_a = WALLET_A
        coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
        receiver_1_puzzlehash = WALLET_A_PUZZLE_HASHES[1]
        receiver_2_puzzlehash = WALLET_A_PUZZLE_HASHES[2]
        receiver_3_puzzlehash = WALLET_A_PUZZLE_HASHES[3]

        blocks = bt.get_consecutive_blocks(
            num_blocks, farmer_reward_puzzle_hash=coinbase_puzzlehash, guarantee_block=True
        )
        full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes

        for block in blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        spend_block = blocks[1]

        spend_coin = None
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                spend_coin = coin

        spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_1_puzzlehash, spend_coin)

        new_blocks = bt.get_consecutive_blocks(
            1,
            blocks[:5],
            seed=b"spend_reorg_coin",
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=spend_bundle,
            guarantee_block=True,
        )

        await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(new_blocks[-1]))

        coin_2 = None
        for coin in new_blocks[-1].additions():
            if coin.puzzle_hash == receiver_1_puzzlehash:
                coin_2 = coin
                break
        assert coin_2 is not None

        spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_2_puzzlehash, coin_2)

        new_blocks = bt.get_consecutive_blocks(
            1,
            new_blocks[:6],
            seed=b"spend_reorg_coin",
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=spend_bundle,
            guarantee_block=True,
        )
        await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(new_blocks[-1]))

        coin_3 = None
        for coin in new_blocks[-1].additions():
            if coin.puzzle_hash == receiver_2_puzzlehash:
                coin_3 = coin
                break
        assert coin_3 is not None

        spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_3_puzzlehash, coin_3)

        new_blocks = bt.get_consecutive_blocks(
            1,
            new_blocks[:7],
            seed=b"spend_reorg_coin",
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=spend_bundle,
            guarantee_block=True,
        )

        await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(new_blocks[-1]))

        coin_4 = None
        for coin in new_blocks[-1].additions():
            if coin.puzzle_hash == receiver_3_puzzlehash:
                coin_4 = coin
                break
        assert coin_4 is not None

    @pytest.mark.asyncio
    async def test_validate_blockchain_spend_reorg_cb_coin(self, two_nodes):
        num_blocks = 15
        wallet_a = WALLET_A
        coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
        receiver_1_puzzlehash = WALLET_A_PUZZLE_HASHES[1]

        blocks = bt.get_consecutive_blocks(num_blocks, farmer_reward_puzzle_hash=coinbase_puzzlehash)
        full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes

        for block in blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # Spends a coinbase created in reorg
        new_blocks = bt.get_consecutive_blocks(
            5,
            blocks[:6],
            seed=b"reorg cb coin",
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            guarantee_block=True,
        )

        for block in new_blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        spend_block = new_blocks[-1]
        spend_coin = None
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                spend_coin = coin
        spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_1_puzzlehash, spend_coin)

        new_blocks = bt.get_consecutive_blocks(
            1,
            new_blocks,
            seed=b"reorg cb coin",
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=spend_bundle,
            guarantee_block=True,
        )

        await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(new_blocks[-1]))

        coins_created = []
        for coin in new_blocks[-1].additions():
            if coin.puzzle_hash == receiver_1_puzzlehash:
                coins_created.append(coin)
        assert len(coins_created) == 1

    @pytest.mark.asyncio
    async def test_validate_blockchain_spend_reorg_since_genesis(self, two_nodes):
        num_blocks = 10
        wallet_a = WALLET_A
        coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
        receiver_1_puzzlehash = WALLET_A_PUZZLE_HASHES[1]

        blocks = bt.get_consecutive_blocks(
            num_blocks, farmer_reward_puzzle_hash=coinbase_puzzlehash, guarantee_block=True
        )
        full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes

        for block in blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        spend_block = blocks[-1]
        spend_coin = None
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                spend_coin = coin
        spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_1_puzzlehash, spend_coin)

        new_blocks = bt.get_consecutive_blocks(
            1, blocks, seed=b"", farmer_reward_puzzle_hash=coinbase_puzzlehash, transaction_data=spend_bundle
        )
        await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(new_blocks[-1]))

        # Spends a coin in a genesis reorg, that was already spent
        new_blocks = bt.get_consecutive_blocks(
            12,
            [],
            seed=b"reorg since genesis",
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
        )
        for block in new_blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        new_blocks = bt.get_consecutive_blocks(
            1,
            new_blocks,
            seed=b"reorg since genesis",
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=spend_bundle,
        )

        await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(new_blocks[-1]))

    @pytest.mark.asyncio
    async def test_assert_my_coin_id(self, two_nodes):
        num_blocks = 10
        wallet_a = WALLET_A
        coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
        receiver_puzzlehash = BURN_PUZZLE_HASH

        # Farm blocks
        blocks = bt.get_consecutive_blocks(
            num_blocks, farmer_reward_puzzle_hash=coinbase_puzzlehash, guarantee_block=True
        )
        full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes
        full_node_1 = full_node_api_1.full_node

        for block in blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # Coinbase that gets spent

        spend_block = blocks[1]
        bad_block = blocks[2]
        spend_coin = None
        bad_spend_coin = None
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                spend_coin = coin
        for coin in list(bad_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                bad_spend_coin = coin
        valid_cvp = ConditionVarPair(ConditionOpcode.ASSERT_MY_COIN_ID, spend_coin.name(), None)
        valid_dic = {valid_cvp.opcode: [valid_cvp]}
        bad_cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_MY_COIN_ID,
            bad_spend_coin.name(),
            None,
        )

        bad_dic = {bad_cvp.opcode: [bad_cvp]}
        bad_spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, spend_coin, bad_dic)

        valid_spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, spend_coin, valid_dic)

        assert bad_spend_bundle is not None
        assert valid_spend_bundle is not None

        # Invalid block bundle
        # Create another block that includes our transaction
        invalid_new_blocks = bt.get_consecutive_blocks(
            1,
            blocks,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=bad_spend_bundle,
            guarantee_block=True,
        )

        # Try to validate that block
        res, err, _ = await full_node_1.blockchain.receive_block(invalid_new_blocks[-1])
        assert res == ReceiveBlockResult.INVALID_BLOCK
        assert err == Err.ASSERT_MY_COIN_ID_FAILED

        # Valid block bundle
        # Create another block that includes our transaction
        new_blocks = bt.get_consecutive_blocks(
            1,
            blocks,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=valid_spend_bundle,
            guarantee_block=True,
        )
        res, err, _ = await full_node_1.blockchain.receive_block(new_blocks[-1])
        assert res == ReceiveBlockResult.NEW_PEAK
        assert err is None


# #
# #     @pytest.mark.asyncio
#     async def test_assert_coin_consumed(self, two_nodes):
#
#         num_blocks = 10
#         wallet_a = WALLET_A
#         coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
#         receiver_puzzlehash = BURN_PUZZLE_HASH
#
#         # Farm blocks
#         blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash)
#         full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes
#         full_node_1 = full_node_api_1.full_node
#
#         for block in blocks:
#             await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
#
#         # Coinbase that gets spent
#         block1 = blocks[1]
#         block2 = blocks[2]
#
#         # This condition requires block2 coinbase to be spent
#         block1_cvp = ConditionVarPair(
#             ConditionOpcode.ASSERT_COIN_CONSUMED,
#             block2.get_coinbase().name(),
#             None,
#         )
#         block1_dic = {block1_cvp.opcode: [block1_cvp]}
#         block1_spend_bundle = wallet_a.generate_signed_transaction(
#             1000, receiver_puzzlehash, block1.get_coinbase(), block1_dic
#         )
#
#         # This condition requires block1 coinbase to be spent
#         block2_cvp = ConditionVarPair(
#             ConditionOpcode.ASSERT_COIN_CONSUMED,
#             block1.get_coinbase().name(),
#             None,
#         )
#         block2_dic = {block2_cvp.opcode: [block2_cvp]}
#         block2_spend_bundle = wallet_a.generate_signed_transaction(
#             1000, receiver_puzzlehash, block2.get_coinbase(), block2_dic
#         )
#
#         # Invalid block bundle
#         assert block1_spend_bundle is not None
#         solo_program = best_solution_program(block1_spend_bundle)
#         aggsig = block1_spend_bundle.aggregated_signature
#
#         # Create another block that includes our transaction
#         dic_h = {11: (solo_program, aggsig)}
#         invalid_new_blocks = bt.get_consecutive_blocks(test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h)
#
#         # Try to validate that block
#         next_block = invalid_new_blocks[11]
#         error = await full_node_1.blockchain._validate_transactions(next_block, next_block.get_fees_coin().amount)
#
#         assert error is Err.ASSERT_COIN_CONSUMED_FAILED
#
#         # bundle_together contains both transactions
#         bundle_together = SpendBundle.aggregate([block1_spend_bundle, block2_spend_bundle])
#         valid_program = best_solution_program(bundle_together)
#         aggsig = bundle_together.aggregated_signature
#
#         # Create another block that includes our transaction
#         dic_h = {11: (valid_program, aggsig)}
#         new_blocks = bt.get_consecutive_blocks(test_constants, 1, blocks[:11], 10, b"1", coinbase_puzzlehash, dic_h)
#
#         # Try to validate newly created block
#         next_block = new_blocks[11]
#         error = await full_node_1.blockchain._validate_transactions(next_block, next_block.get_fees_coin().amount)
#
#         assert error is None
#
#     @pytest.mark.asyncio
#     async def test_assert_block_index_exceeds(self, two_nodes):
#
#         num_blocks = 10
#         wallet_a = WALLET_A
#         coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
#         receiver_puzzlehash = BURN_PUZZLE_HASH
#
#         # Farm blocks
#         blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash)
#         full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes
#         full_node_1 = full_node_api_1.full_node
#
#         for block in blocks:
#             await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
#
#         # Coinbase that gets spent
#         block1 = blocks[1]
#
#         # This condition requires block1 coinbase to be spent after index 11
#         block1_cvp = ConditionVarPair(ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS, int_to_bytes(11), None)
#         block1_dic = {block1_cvp.opcode: [block1_cvp]}
#         block1_spend_bundle = wallet_a.generate_signed_transaction(
#             1000, receiver_puzzlehash, block1.get_coinbase(), block1_dic
#         )
#
#         # program that will be sent to early
#         assert block1_spend_bundle is not None
#         program = best_solution_program(block1_spend_bundle)
#         aggsig = block1_spend_bundle.aggregated_signature
#
#         # Create another block that includes our transaction
#         dic_h = {11: (program, aggsig)}
#         invalid_new_blocks = bt.get_consecutive_blocks(test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h)
#
#         # Try to validate that block at index 11
#         next_block = invalid_new_blocks[11]
#         error = await full_node_1.blockchain._validate_transactions(next_block, next_block.get_fees_coin().amount)
#
#         assert error is Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED
#
#         dic_h = {12: (program, aggsig)}
#         valid_new_blocks = bt.get_consecutive_blocks(
#             test_constants, 2, blocks[:11], 10, b"", coinbase_puzzlehash, dic_h
#         )
#
#         for block in valid_new_blocks:
#             await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
#
#         # Try to validate that block at index 12
#         next_block = valid_new_blocks[12]
#
#         error = await full_node_1.blockchain._validate_transactions(next_block, next_block.get_fees_coin().amount)
#
#         assert error is None
#
#     @pytest.mark.asyncio
#     async def test_assert_block_age_exceeds(self, two_nodes):
#
#         num_blocks = 10
#         wallet_a = WALLET_A
#         coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
#         receiver_puzzlehash = BURN_PUZZLE_HASH
#
#         # Farm blocks
#         blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash)
#         full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes
#         full_node_1 = full_node_api_1.full_node
#
#         for block in blocks:
#             await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
#
#         # Coinbase that gets spent
#         block1 = blocks[1]
#
#         # This condition requires block1 coinbase to be spent more than 10 block after it was farmed
#         # block index has to be greater than (1 + 10 = 11)
#         block1_cvp = ConditionVarPair(ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS, int_to_bytes(10), None)
#         block1_dic = {block1_cvp.opcode: [block1_cvp]}
#         block1_spend_bundle = wallet_a.generate_signed_transaction(
#             1000, receiver_puzzlehash, block1.get_coinbase(), block1_dic
#         )
#
#         # program that will be sent to early
#         assert block1_spend_bundle is not None
#         program = best_solution_program(block1_spend_bundle)
#         aggsig = block1_spend_bundle.aggregated_signature
#
#         # Create another block that includes our transaction
#         dic_h = {11: (program, aggsig)}
#         invalid_new_blocks = bt.get_consecutive_blocks(test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h)
#
#         # Try to validate that block at index 11
#         next_block = invalid_new_blocks[11]
#         error = await full_node_1.blockchain._validate_transactions(next_block, next_block.get_fees_coin().amount)
#
#         assert error is Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED
#
#         dic_h = {12: (program, aggsig)}
#         valid_new_blocks = bt.get_consecutive_blocks(
#             test_constants, 2, blocks[:11], 10, b"", coinbase_puzzlehash, dic_h
#         )
#
#         for block in valid_new_blocks:
#             await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
#
#         # Try to validate that block at index 12
#         next_block = valid_new_blocks[12]
#
#         error = await full_node_1.blockchain._validate_transactions(next_block, next_block.get_fees_coin().amount)
#
#         assert error is None
#
#     @pytest.mark.asyncio
#     async def test_assert_time_exceeds(self, two_nodes):
#
#         num_blocks = 10
#         wallet_a = WALLET_A
#         coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
#         receiver_puzzlehash = BURN_PUZZLE_HASH
#
#         # Farm blocks
#         blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash)
#         full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes
#         full_node_1 = full_node_api_1.full_node
#
#         for block in blocks:
#             await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
#
#         # Coinbase that gets spent
#         block1 = blocks[1]
#
#         # This condition requires block1 coinbase to be spent after 3 seconds from now
#         current_time_plus3 = uint64(int(time.time() * 1000) + 3000)
#         block1_cvp = ConditionVarPair(ConditionOpcode.ASSERT_TIME_EXCEEDS, int_to_bytes(current_time_plus3), None)
#         block1_dic = {block1_cvp.opcode: [block1_cvp]}
#         block1_spend_bundle = wallet_a.generate_signed_transaction(
#             1000, receiver_puzzlehash, block1.get_coinbase(), block1_dic
#         )
#
#         # program that will be sent to early
#         assert block1_spend_bundle is not None
#         program = best_solution_program(block1_spend_bundle)
#         aggsig = block1_spend_bundle.aggregated_signature
#
#         # Create another block that includes our transaction
#         dic_h = {11: (program, aggsig)}
#         invalid_new_blocks = bt.get_consecutive_blocks(test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h)
#
#         # Try to validate that block before 3 sec
#         next_block = invalid_new_blocks[11]
#         error = await full_node_1.blockchain._validate_transactions(next_block, next_block.get_fees_coin().amount)
#
#         assert error is Err.ASSERT_TIME_EXCEEDS_FAILED
#
#         # wait 3 sec to pass
#         await asyncio.sleep(3.1)
#
#         dic_h = {12: (program, aggsig)}
#         valid_new_blocks = bt.get_consecutive_blocks(
#             test_constants, 2, blocks[:11], 10, b"", coinbase_puzzlehash, dic_h
#         )
#
#         for block in valid_new_blocks:
#             await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
#
#         # Try to validate that block after 3 sec have passed
#         next_block = valid_new_blocks[12]
#
#         error = await full_node_1.blockchain._validate_transactions(next_block, next_block.get_fees_coin().amount)
#
#         assert error is None

# @pytest.mark.asyncio
# async def test_invalid_filter(self, two_nodes):
#     num_blocks = 10
#     wallet_a = WALLET_A
#     coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
#     receiver_puzzlehash = BURN_PUZZLE_HASH
#
#     blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash)
#     full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes
#     full_node_1 = full_node_api_1.full_node
#
#     for block in blocks:
#         await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))
#
#     spent_block = blocks[1]
#
#     spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, spent_block.get_coinbase())
#
#     assert spend_bundle is not None
#     tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle)
#     await full_node_api_1.respond_transaction(tx)
#
#     sb = full_node_1.mempool_manager.get_spendbundle(spend_bundle.name())
#     assert sb is spend_bundle
#
#     last_block = blocks[10]
#     next_spendbundle = await full_node_1.mempool_manager.create_bundle_from_mempool(last_block.header)
#     assert next_spendbundle is not None
#
#     program = best_solution_program(next_spendbundle)
#     aggsig = next_spendbundle.aggregated_signature
#
#     dic_h = {11: (program, aggsig)}
#     new_blocks = bt.get_consecutive_blocks(test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h)
#
#     next_block = new_blocks[11]
#
#     bad_header = HeaderData(
#         next_block.header.data.height,
#         next_block.header.data.prev_header_hash,
#         next_block.header.data.timestamp,
#         bytes32(bytes([3] * 32)),
#         next_block.header.data.proof_of_space_hash,
#         next_block.header.data.weight,
#         next_block.header.data.total_iters,
#         next_block.header.data.additions_root,
#         next_block.header.data.removals_root,
#         next_block.header.data.farmer_rewards_puzzle_hash,
#         next_block.header.data.total_transaction_fees,
#         next_block.header.data.pool_target,
#         next_block.header.data.aggregated_signature,
#         next_block.header.data.cost,
#         next_block.header.data.extension_data,
#         next_block.header.data.generator_hash,
#     )
#     bad_block = FullBlock(
#         next_block.proof_of_space,
#         next_block.proof_of_time,
#         Header(
#             bad_header,
#             bt.get_plot_signature(bad_header, next_block.proof_of_space.plot_public_key),
#         ),
#         next_block.transactions_generator,
#         next_block.transactions_filter,
#     )
#     result, removed, error_code = await full_node_1.blockchain.receive_block(bad_block)
#     assert result == ReceiveBlockResult.INVALID_BLOCK
#     assert error_code == Err.INVALID_TRANSACTIONS_FILTER_HASH
#
#     result, removed, error_code = await full_node_1.blockchain.receive_block(next_block)
#     assert result == ReceiveBlockResult.NEW_TIP
#
# @pytest.mark.asyncio
# async def test_assert_fee_condition(self, two_nodes):
#
#     num_blocks = 10
#     wallet_a = WALLET_A
#     coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
#     receiver_puzzlehash = BURN_PUZZLE_HASH
#
#     # Farm blocks
#     blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash)
#     full_node_api_1, full_node_api_2, server_1, server_2 = two_nodes
#     full_node_1 = full_node_api_1.full_node
#
#     for block in blocks:
#         await full_node_api_1.respond_block(full_node_protocol.RespondSubBlock(block))
#
#     # Coinbase that gets spent
#     block1 = blocks[1]
#
#     # This condition requires fee to be 10 mojo
#     cvp_fee = ConditionVarPair(ConditionOpcode.ASSERT_FEE, int_to_bytes(10), None)
#     block1_dic = {cvp_fee.opcode: [cvp_fee]}
#     # This spendbundle has 9 mojo as fee
#     invalid_spend_bundle = wallet_a.generate_signed_transaction(
#         1000, receiver_puzzlehash, block1.get_coinbase(), block1_dic, 9
#     )
#
#     assert invalid_spend_bundle is not None
#     program = best_solution_program(invalid_spend_bundle)
#     aggsig = invalid_spend_bundle.aggregated_signature
#
#     # Create another block that includes our transaction
#     dic_h = {11: (program, aggsig)}
#     invalid_new_blocks = bt.get_consecutive_blocks(
#         test_constants,
#         1,
#         blocks,
#         10,
#         b"",
#         coinbase_puzzlehash,
#         dic_h,
#         fees=uint64(9),
#     )
#
#     # Try to validate that block at index 11
#     next_block = invalid_new_blocks[11]
#     error = await full_node_1.blockchain._validate_transactions(next_block, next_block.get_fees_coin().amount)
#
#     assert error is Err.ASSERT_FEE_CONDITION_FAILED
#
#     # This condition requires fee to be 10 mojo
#     cvp_fee = ConditionVarPair(ConditionOpcode.ASSERT_FEE, int_to_bytes(10), None)
#     condition_dict = {cvp_fee.opcode: [cvp_fee]}
#     valid_spend_bundle = wallet_a.generate_signed_transaction(
#         1000, receiver_puzzlehash, block1.get_coinbase(), condition_dict, 10
#     )
#
#     assert valid_spend_bundle is not None
#     valid_program = best_solution_program(valid_spend_bundle)
#     aggsig = valid_spend_bundle.aggregated_signature
#
#     dic_h = {11: (valid_program, aggsig)}
#     valid_new_blocks = bt.get_consecutive_blocks(
#         test_constants,
#         1,
#         blocks[:11],
#         10,
#         b"",
#         coinbase_puzzlehash,
#         dic_h,
#         fees=uint64(10),
#     )
#
#     next_block = valid_new_blocks[11]
#     fee_base = calculate_base_fee(next_block.height)
#     error = await full_node_1.blockchain._validate_transactions(next_block, fee_base)
#
#     assert error is None
#
#     for block in valid_new_blocks:
#         await full_node_api_1.respond_block(full_node_protocol.RespondSubBlock(block))
