import asyncio
import pytest
from clvm.casts import int_to_bytes
import random
from typing import Dict
from secrets import token_bytes

from src.protocols import full_node_protocol as fnp
from src.types.peer_info import PeerInfo
from src.types.hashable.SpendBundle import SpendBundle
from src.util.bundle_tools import best_solution_program
from src.util.ints import uint16, uint32, uint64
from src.types.ConditionVarPair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from tests.setup_nodes import setup_two_nodes, test_constants, bt
from tests.wallet_tools import WalletTool


num_blocks = 5


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="module")
async def two_nodes():
    async for _ in setup_two_nodes({"COINBASE_FREEZE_PERIOD": 0}):
        yield _


@pytest.fixture(scope="module")
async def wallet_blocks(two_nodes):
    """
    Sets up the node with 10 blocks, and returns a payer and payee wallet.
    """
    full_node_1, _, _, _ = two_nodes
    wallet_a = WalletTool()
    coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
    wallet_receiver = WalletTool()
    blocks = bt.get_consecutive_blocks(
        test_constants, num_blocks, [], 10, reward_puzzlehash=coinbase_puzzlehash
    )
    for i in range(1, num_blocks):
        async for _ in full_node_1.respond_block(fnp.RespondBlock(blocks[i])):
            pass

    return wallet_a, wallet_receiver, blocks


class TestFullNode:
    @pytest.mark.asyncio
    async def test_new_tip(self, two_nodes, wallet_blocks):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        _, _, blocks = wallet_blocks

        await server_2.start_client(
            PeerInfo(server_1._host, uint16(server_1._port)), None
        )
        await asyncio.sleep(2)  # Allow connections to get made

        new_tip_1 = fnp.NewTip(
            blocks[-1].height, blocks[-1].weight, blocks[-1].header_hash
        )
        msgs_1 = [x async for x in full_node_1.new_tip(new_tip_1)]

        assert len(msgs_1) == 1
        assert msgs_1[0].message.data == fnp.RequestBlock(
            uint32(num_blocks), blocks[-1].header_hash
        )

        new_tip_2 = fnp.NewTip(
            blocks[3].height, blocks[3].weight, blocks[3].header_hash
        )
        msgs_2 = [x async for x in full_node_1.new_tip(new_tip_2)]
        assert len(msgs_2) == 0

    @pytest.mark.asyncio
    async def test_new_transaction(self, two_nodes, wallet_blocks):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        wallet_a, wallet_receiver, blocks = wallet_blocks
        conditions_dict: Dict = {ConditionOpcode.CREATE_COIN: []}

        # Mempool has capacity of 100, make 110 unspents that we can use
        puzzle_hashes = []
        for _ in range(110):
            receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
            puzzle_hashes.append(receiver_puzzlehash)
            output = ConditionVarPair(
                ConditionOpcode.CREATE_COIN, receiver_puzzlehash, int_to_bytes(1000)
            )
            conditions_dict[ConditionOpcode.CREATE_COIN].append(output)

        spend_bundle = wallet_a.generate_signed_transaction(
            100,
            receiver_puzzlehash,
            blocks[1].body.coinbase,
            condition_dic=conditions_dict,
        )
        assert spend_bundle is not None

        new_transaction = fnp.NewTransaction(
            spend_bundle.get_hash(), uint64(100), uint64(100)
        )
        # Not seen
        msgs = [x async for x in full_node_1.new_transaction(new_transaction)]
        assert len(msgs) == 1
        assert msgs[0].message.data == fnp.RequestTransaction(spend_bundle.get_hash())

        respond_transaction_2 = fnp.RespondTransaction(spend_bundle)
        [x async for x in full_node_1.respond_transaction(respond_transaction_2)]

        program = best_solution_program(spend_bundle)
        aggsig = spend_bundle.aggregated_signature

        dic_h = {5: (program, aggsig)}
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()
        blocks_new = bt.get_consecutive_blocks(
            test_constants,
            1,
            blocks[:-1],
            10,
            reward_puzzlehash=coinbase_puzzlehash,
            transaction_data_at_height=dic_h,
        )
        # Already seen
        msgs = [x async for x in full_node_1.new_transaction(new_transaction)]
        assert len(msgs) == 0

        # Farm one block
        [_ async for _ in full_node_1.respond_block(fnp.RespondBlock(blocks_new[-1]))]

        spend_bundles = []
        total_fee = 0
        # Fill mempool
        for puzzle_hash in puzzle_hashes:
            coin_record = (
                await full_node_1.unspent_store.get_coin_records_by_puzzle_hash(
                    puzzle_hash, blocks_new[-1].header
                )
            )[0]
            receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
            fee = random.randint(0, 499)
            spend_bundle = wallet_receiver.generate_signed_transaction(
                500, receiver_puzzlehash, coin_record.coin, fee=fee
            )
            respond_transaction = fnp.RespondTransaction(spend_bundle)
            res = [
                x async for x in full_node_1.respond_transaction(respond_transaction)
            ]

            # Added to mempool
            if len(res) > 0:
                total_fee += fee
                spend_bundles.append(spend_bundle)

        # Mempool is full
        new_transaction = fnp.NewTransaction(token_bytes(32), uint64(10000), uint64(1))
        msgs = [x async for x in full_node_1.new_transaction(new_transaction)]
        assert len(msgs) == 0

        agg = SpendBundle.aggregate(spend_bundles)
        program = best_solution_program(agg)
        aggsig = agg.aggregated_signature

        dic_h = {6: (program, aggsig)}
        coinbase_puzzlehash = wallet_a.get_new_puzzlehash()

        blocks_new = bt.get_consecutive_blocks(
            test_constants,
            1,
            blocks_new,
            10,
            reward_puzzlehash=coinbase_puzzlehash,
            transaction_data_at_height=dic_h,
            fees=uint64(total_fee),
        )
        # Farm one block to clear mempool
        [_ async for _ in full_node_1.respond_block(fnp.RespondBlock(blocks_new[-1]))]

    @pytest.mark.asyncio
    async def test_request_respond_transaction(self, two_nodes, wallet_blocks):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        wallet_a, wallet_receiver, blocks = wallet_blocks

        tx_id = token_bytes(32)
        request_transaction = fnp.RequestTransaction(tx_id)
        msgs = [x async for x in full_node_1.request_transaction(request_transaction)]
        assert len(msgs) == 1
        assert msgs[0].message.data == fnp.RejectTransactionRequest(tx_id)

        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()
        spend_bundle = wallet_a.generate_signed_transaction(
            100, receiver_puzzlehash, blocks[2].body.coinbase,
        )
        assert spend_bundle is not None
        respond_transaction = fnp.RespondTransaction(spend_bundle)
        prop = [x async for x in full_node_1.respond_transaction(respond_transaction)]
        assert len(prop) == 1
        assert isinstance(prop[0].message.data, fnp.NewTransaction)

        request_transaction = fnp.RequestTransaction(spend_bundle.get_hash())
        msgs = [x async for x in full_node_1.request_transaction(request_transaction)]
        assert len(msgs) == 1
        assert msgs[0].message.data == fnp.RespondTransaction(spend_bundle)

    @pytest.mark.asyncio
    async def test_respond_transaction_fail(self, two_nodes, wallet_blocks):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        wallet_a, wallet_receiver, blocks = wallet_blocks

        tx_id = token_bytes(32)
        request_transaction = fnp.RequestTransaction(tx_id)
        msgs = [x async for x in full_node_1.request_transaction(request_transaction)]
        assert len(msgs) == 1
        assert msgs[0].message.data == fnp.RejectTransactionRequest(tx_id)

        receiver_puzzlehash = wallet_receiver.get_new_puzzlehash()

        # Invalid transaction does not propagate
        spend_bundle = wallet_a.generate_signed_transaction(
            100000000000000, receiver_puzzlehash, blocks[3].body.coinbase,
        )
        assert spend_bundle is not None
        respond_transaction = fnp.RespondTransaction(spend_bundle)
        assert (
            len([x async for x in full_node_1.respond_transaction(respond_transaction)])
            == 0
        )

    @pytest.mark.asyncio
    async def test_new_pot(self, two_nodes, wallet_blocks):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        wallet_a, wallet_receiver, blocks = wallet_blocks
