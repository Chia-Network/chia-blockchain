import asyncio
import time
from typing import Optional
import pytest
from clvm.casts import int_to_bytes

from src.types.ConditionVarPair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from src.util.bundle_tools import best_solution_program
from src.server.outbound_message import OutboundMessage
from src.protocols import full_node_protocol
from src.types.full_block import FullBlock
from src.types.hashable.SpendBundle import SpendBundle
from src.util.ConsensusError import Err
from src.util.ints import uint64
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from tests.wallet_tools import WalletTool


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestBlockchainTransactions:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes({"COINBASE_FREEZE_PERIOD": 0}):
            yield _

    @pytest.fixture(scope="function")
    async def two_nodes_standard_freeze(self):
        async for _ in setup_two_nodes({"COINBASE_FREEZE_PERIOD": 200}):
            yield _

    @pytest.mark.asyncio
    async def test_basic_blockchain_tx(self, two_nodes):
        num_blocks = 10
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        spent_block = blocks[1]

        spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, spent_block.body.coinbase
        )

        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(
            spend_bundle
        )
        async for _ in full_node_1.respond_transaction(tx):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "new_transaction"

        sb = await full_node_1.mempool_manager.get_spendbundle(spend_bundle.name())
        assert sb is spend_bundle

        last_block = blocks[10]
        next_spendbundle = await full_node_1.mempool_manager.create_bundle_for_tip(
            last_block.header
        )
        assert next_spendbundle is not None

        program = best_solution_program(next_spendbundle)
        aggsig = next_spendbundle.aggregated_signature

        dic_h = {11: (program, aggsig)}
        new_blocks = bt.get_consecutive_blocks(
            test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h
        )

        next_block = new_blocks[11]
        async for _ in full_node_1.respond_block(
            full_node_protocol.RespondBlock(next_block)
        ):
            pass

        tips = full_node_1.blockchain.get_current_tips()
        assert next_block.header in tips

        added_coins = next_spendbundle.additions()

        # Two coins are added, main spend and change
        assert len(added_coins) == 2
        for coin in added_coins:
            unspent = await full_node_1.unspent_store.get_coin_record(
                coin.name(), next_block.header
            )
            assert unspent is not None

        full_tips = await full_node_1.blockchain.get_full_tips()
        in_full_tips = False

        farmed_block: Optional[FullBlock] = None
        for tip in full_tips:
            if tip.header == next_block.header:
                in_full_tips = True
                farmed_block = tip

        assert in_full_tips
        assert farmed_block is not None
        assert farmed_block.body.transactions == program
        assert farmed_block.body.aggregated_signature == aggsig

    @pytest.mark.asyncio
    async def test_validate_blockchain_with_double_spend(self, two_nodes):

        num_blocks = 10
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        spent_block = blocks[1]

        spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, spent_block.body.coinbase
        )
        spend_bundle_double = wallet_a.generate_signed_transaction(
            1001, receiver_puzzlehash, spent_block.body.coinbase
        )

        block_spendbundle = SpendBundle.aggregate([spend_bundle, spend_bundle_double])
        program = best_solution_program(block_spendbundle)
        aggsig = block_spendbundle.aggregated_signature

        dic_h = {11: (program, aggsig)}
        new_blocks = bt.get_consecutive_blocks(
            test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h
        )

        next_block = new_blocks[11]
        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is Err.DOUBLE_SPEND

    @pytest.mark.asyncio
    async def test_validate_blockchain_with_double_output(self, two_nodes):

        num_blocks = 10
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        spent_block = blocks[1]

        spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, spent_block.body.coinbase
        )
        spend_bundle_double = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, spent_block.body.coinbase
        )

        block_spendbundle = SpendBundle.aggregate([spend_bundle, spend_bundle_double])
        program = best_solution_program(block_spendbundle)
        aggsig = block_spendbundle.aggregated_signature

        dic_h = {11: (program, aggsig)}
        new_blocks = bt.get_consecutive_blocks(
            test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h
        )

        next_block = new_blocks[11]
        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is Err.DUPLICATE_OUTPUT

    @pytest.mark.asyncio
    async def test_assert_my_coin_id(self, two_nodes):

        num_blocks = 10
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        # Farm blocks
        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        # Coinbase that gets spent
        spent_block = blocks[1]
        bad_block = blocks[2]
        valid_cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_MY_COIN_ID, spent_block.body.coinbase.name(), None
        )
        valid_dic = {valid_cvp.opcode: [valid_cvp]}
        bad_cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_MY_COIN_ID, bad_block.body.coinbase.name(), None
        )

        bad_dic = {bad_cvp.opcode: [bad_cvp]}
        bad_spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, spent_block.body.coinbase, bad_dic
        )

        valid_spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, spent_block.body.coinbase, valid_dic
        )

        # Invalid block bundle
        assert bad_spend_bundle is not None
        invalid_program = best_solution_program(bad_spend_bundle)
        aggsig = bad_spend_bundle.aggregated_signature

        # Create another block that includes our transaction
        dic_h = {11: (invalid_program, aggsig)}
        invalid_new_blocks = bt.get_consecutive_blocks(
            test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h
        )

        # Try to validate that block
        next_block = invalid_new_blocks[11]
        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is Err.ASSERT_MY_COIN_ID_FAILED

        # Valid block bundle
        assert valid_spend_bundle is not None
        valid_program = best_solution_program(valid_spend_bundle)
        aggsig = valid_spend_bundle.aggregated_signature

        # Create another block that includes our transaction
        dic_h = {11: (valid_program, aggsig)}
        new_blocks = bt.get_consecutive_blocks(
            test_constants, 1, blocks[:11], 10, b"1", coinbase_puzzlehash, dic_h
        )
        next_block = new_blocks[11]
        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )
        assert error is None

    @pytest.mark.asyncio
    async def test_assert_coin_consumed(self, two_nodes):

        num_blocks = 10
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        # Farm blocks
        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        # Coinbase that gets spent
        block1 = blocks[1]
        block2 = blocks[2]

        # This condition requires block2 coinbase to be spent
        block1_cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_COIN_CONSUMED, block2.body.coinbase.name(), None
        )
        block1_dic = {block1_cvp.opcode: [block1_cvp]}
        block1_spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block1.body.coinbase, block1_dic
        )

        # This condition requires block1 coinbase to be spent
        block2_cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_COIN_CONSUMED, block1.body.coinbase.name(), None
        )
        block2_dic = {block2_cvp.opcode: [block2_cvp]}
        block2_spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block2.body.coinbase, block2_dic
        )

        # Invalid block bundle
        assert block1_spend_bundle is not None
        solo_program = best_solution_program(block1_spend_bundle)
        aggsig = block1_spend_bundle.aggregated_signature

        # Create another block that includes our transaction
        dic_h = {11: (solo_program, aggsig)}
        invalid_new_blocks = bt.get_consecutive_blocks(
            test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h
        )

        # Try to validate that block
        next_block = invalid_new_blocks[11]
        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is Err.ASSERT_COIN_CONSUMED_FAILED

        # bundle_together contains both transactions
        bundle_together = SpendBundle.aggregate(
            [block1_spend_bundle, block2_spend_bundle]
        )
        valid_program = best_solution_program(bundle_together)
        aggsig = bundle_together.aggregated_signature

        # Create another block that includes our transaction
        dic_h = {11: (valid_program, aggsig)}
        new_blocks = bt.get_consecutive_blocks(
            test_constants, 1, blocks[:11], 10, b"1", coinbase_puzzlehash, dic_h
        )

        # Try to validate newly created block
        next_block = new_blocks[11]
        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is None

    @pytest.mark.asyncio
    async def test_assert_block_index_exceeds(self, two_nodes):

        num_blocks = 10
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        # Farm blocks
        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        # Coinbase that gets spent
        block1 = blocks[1]

        # This condition requires block1 coinbase to be spent after index 11
        block1_cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS, int_to_bytes(11), None
        )
        block1_dic = {block1_cvp.opcode: [block1_cvp]}
        block1_spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block1.body.coinbase, block1_dic
        )

        # program that will be sent to early
        assert block1_spend_bundle is not None
        program = best_solution_program(block1_spend_bundle)
        aggsig = block1_spend_bundle.aggregated_signature

        # Create another block that includes our transaction
        dic_h = {11: (program, aggsig)}
        invalid_new_blocks = bt.get_consecutive_blocks(
            test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h
        )

        # Try to validate that block at index 11
        next_block = invalid_new_blocks[11]
        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is Err.ASSERT_BLOCK_INDEX_EXCEEDS_FAILED

        dic_h = {12: (program, aggsig)}
        valid_new_blocks = bt.get_consecutive_blocks(
            test_constants, 2, blocks[:11], 10, b"", coinbase_puzzlehash, dic_h
        )

        for block in valid_new_blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        # Try to validate that block at index 12
        next_block = valid_new_blocks[12]

        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is None

    @pytest.mark.asyncio
    async def test_assert_block_age_exceeds(self, two_nodes):

        num_blocks = 10
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        # Farm blocks
        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        # Coinbase that gets spent
        block1 = blocks[1]

        # This condition requires block1 coinbase to be spent more than 10 block after it was farmed
        # block index has to be greater than (1 + 10 = 11)
        block1_cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS, int_to_bytes(10), None
        )
        block1_dic = {block1_cvp.opcode: [block1_cvp]}
        block1_spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block1.body.coinbase, block1_dic
        )

        # program that will be sent to early
        assert block1_spend_bundle is not None
        program = best_solution_program(block1_spend_bundle)
        aggsig = block1_spend_bundle.aggregated_signature

        # Create another block that includes our transaction
        dic_h = {11: (program, aggsig)}
        invalid_new_blocks = bt.get_consecutive_blocks(
            test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h
        )

        # Try to validate that block at index 11
        next_block = invalid_new_blocks[11]
        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is Err.ASSERT_BLOCK_AGE_EXCEEDS_FAILED

        dic_h = {12: (program, aggsig)}
        valid_new_blocks = bt.get_consecutive_blocks(
            test_constants, 2, blocks[:11], 10, b"", coinbase_puzzlehash, dic_h
        )

        for block in valid_new_blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        # Try to validate that block at index 12
        next_block = valid_new_blocks[12]

        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is None

    @pytest.mark.asyncio
    async def test_assert_time_exceeds(self, two_nodes):

        num_blocks = 10
        wallet_a = WalletTool()
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        wallet_receiver = WalletTool()
        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        # Farm blocks
        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, b"", coinbase_puzzlehash
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        # Coinbase that gets spent
        block1 = blocks[1]

        # This condition requires block1 coinbase to be spent after 3 seconds from now
        current_time_plus3 = uint64(int(time.time() * 1000) + 3000)
        block1_cvp = ConditionVarPair(
            ConditionOpcode.ASSERT_TIME_EXCEEDS, int_to_bytes(current_time_plus3), None
        )
        block1_dic = {block1_cvp.opcode: [block1_cvp]}
        block1_spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, block1.body.coinbase, block1_dic
        )

        # program that will be sent to early
        assert block1_spend_bundle is not None
        program = best_solution_program(block1_spend_bundle)
        aggsig = block1_spend_bundle.aggregated_signature

        # Create another block that includes our transaction
        dic_h = {11: (program, aggsig)}
        invalid_new_blocks = bt.get_consecutive_blocks(
            test_constants, 1, blocks, 10, b"", coinbase_puzzlehash, dic_h
        )

        # Try to validate that block before 3 sec
        next_block = invalid_new_blocks[11]
        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is Err.ASSERT_TIME_EXCEEDS_FAILED

        # wait 3 sec to pass
        await asyncio.sleep(3.1)

        dic_h = {12: (program, aggsig)}
        valid_new_blocks = bt.get_consecutive_blocks(
            test_constants, 2, blocks[:11], 10, b"", coinbase_puzzlehash, dic_h
        )

        for block in valid_new_blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        # Try to validate that block after 3 sec have passed
        next_block = valid_new_blocks[12]

        error = await full_node_1.blockchain._validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is None
