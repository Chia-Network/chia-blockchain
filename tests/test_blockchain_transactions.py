import asyncio
from typing import Optional
import pytest

from src.farming.farming_tools import best_solution_program
from src.server.outbound_message import OutboundMessage
from src.protocols import peer_protocol
from src.types.full_block import FullBlock
from src.types.hashable.SpendBundle import SpendBundle
from src.util.ConsensusError import Err
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
            async for _ in full_node_1.block(peer_protocol.Block(block)):
                pass

        spent_block = blocks[1]

        spend_bundle = wallet_a.generate_signed_transaction(
            1000, receiver_puzzlehash, spent_block.body.coinbase
        )

        assert spend_bundle is not None
        tx: peer_protocol.Transaction = peer_protocol.Transaction(spend_bundle)
        async for _ in full_node_1.transaction(tx):
            outbound: OutboundMessage = _
            # Maybe transaction means that it's accepted in mempool
            assert outbound.message.function == "maybe_transaction"

        sb = await full_node_1.mempool.get_spendbundle(spend_bundle.name())
        assert sb is spend_bundle

        last_block = blocks[10]
        next_spendbundle = await full_node_1.mempool.create_bundle_for_tip(
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
        async for _ in full_node_1.block(peer_protocol.Block(next_block)):
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
            async for _ in full_node_1.block(peer_protocol.Block(block)):
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
        error = await full_node_1.blockchain.validate_transactions(
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
            async for _ in full_node_1.block(peer_protocol.Block(block)):
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
        error = await full_node_1.blockchain.validate_transactions(
            next_block, next_block.body.fees_coin.amount
        )

        assert error is Err.DUPLICATE_OUTPUT
