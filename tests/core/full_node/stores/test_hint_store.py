from __future__ import annotations

import logging

import pytest
from clvm.casts import int_to_bytes

from chia.full_node.hint_store import HintStore
from chia.protocols.full_node_protocol import RespondBlock
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from tests.util.db_connection import DBConnection

log = logging.getLogger(__name__)


class TestHintStore:
    @pytest.mark.asyncio
    async def test_basic_store(self, db_version):
        async with DBConnection(db_version) as db_wrapper:
            hint_store = await HintStore.create(db_wrapper)
            hint_0 = 32 * b"\0"
            hint_1 = 32 * b"\1"
            not_existing_hint = 32 * b"\3"

            coin_id_0 = 32 * b"\4"
            coin_id_1 = 32 * b"\5"
            coin_id_2 = 32 * b"\6"

            hints = [(coin_id_0, hint_0), (coin_id_1, hint_0), (coin_id_2, hint_1)]
            await hint_store.add_hints(hints)
            coins_for_hint_0 = await hint_store.get_coin_ids(hint_0)

            assert coin_id_0 in coins_for_hint_0
            assert coin_id_1 in coins_for_hint_0

            coins_for_hint_1 = await hint_store.get_coin_ids(hint_1)
            assert coin_id_2 in coins_for_hint_1

            coins_for_non_hint = await hint_store.get_coin_ids(not_existing_hint)
            assert coins_for_non_hint == []

    @pytest.mark.asyncio
    async def test_duplicate_coins(self, db_version):
        async with DBConnection(db_version) as db_wrapper:
            hint_store = await HintStore.create(db_wrapper)
            hint_0 = 32 * b"\0"
            hint_1 = 32 * b"\1"

            coin_id_0 = 32 * b"\4"

            hints = [(coin_id_0, hint_0), (coin_id_0, hint_1)]
            await hint_store.add_hints(hints)
            coins_for_hint_0 = await hint_store.get_coin_ids(hint_0)
            assert coin_id_0 in coins_for_hint_0

            coins_for_hint_1 = await hint_store.get_coin_ids(hint_1)
            assert coin_id_0 in coins_for_hint_1

    @pytest.mark.asyncio
    async def test_duplicate_hints(self, db_version):
        async with DBConnection(db_version) as db_wrapper:
            hint_store = await HintStore.create(db_wrapper)
            hint_0 = 32 * b"\0"
            hint_1 = 32 * b"\1"

            coin_id_0 = 32 * b"\4"
            coin_id_1 = 32 * b"\5"

            hints = [(coin_id_0, hint_0), (coin_id_1, hint_0)]
            await hint_store.add_hints(hints)
            coins_for_hint_0 = await hint_store.get_coin_ids(hint_0)
            assert coin_id_0 in coins_for_hint_0
            assert coin_id_1 in coins_for_hint_0

            coins_for_hint_1 = await hint_store.get_coin_ids(hint_1)
            assert coins_for_hint_1 == []

    @pytest.mark.asyncio
    async def test_duplicates(self, db_version):
        async with DBConnection(db_version) as db_wrapper:
            hint_store = await HintStore.create(db_wrapper)
            hint_0 = 32 * b"\0"
            coin_id_0 = 32 * b"\4"

            for i in range(0, 2):
                hints = [(coin_id_0, hint_0), (coin_id_0, hint_0)]
                await hint_store.add_hints(hints)
            coins_for_hint_0 = await hint_store.get_coin_ids(hint_0)
            assert coin_id_0 in coins_for_hint_0

            async with db_wrapper.reader_no_transaction() as conn:
                cursor = await conn.execute("SELECT COUNT(*) FROM hints")
                rows = await cursor.fetchall()

            if db_wrapper.db_version == 2:
                # even though we inserted the pair multiple times, there's only one
                # entry in the DB
                assert rows[0][0] == 1
            else:
                # we get one copy for each duplicate
                assert rows[0][0] == 4

    @pytest.mark.asyncio
    async def test_hints_in_blockchain(self, wallet_nodes):  # noqa: F811
        full_node_1, full_node_2, server_1, server_2, wallet_a, wallet_receiver, bt = wallet_nodes

        blocks = bt.get_consecutive_blocks(
            5,
            block_list_input=[],
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        for block in blocks:
            await full_node_1.full_node.respond_block(RespondBlock(block), None)

        wt: WalletTool = bt.get_pool_wallet_tool()
        puzzle_hash = bytes32(32 * b"\0")
        amount = int_to_bytes(1)
        hint = bytes32(32 * b"\5")
        coin_spent = list(blocks[-1].get_included_reward_coins())[0]
        condition_dict = {
            ConditionOpcode.CREATE_COIN: [ConditionWithArgs(ConditionOpcode.CREATE_COIN, [puzzle_hash, amount, hint])]
        }
        tx: SpendBundle = wt.generate_signed_transaction(
            10,
            wt.get_new_puzzlehash(),
            coin_spent,
            condition_dic=condition_dict,
        )

        blocks = bt.get_consecutive_blocks(
            10, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )

        for block in blocks[-10:]:
            await full_node_1.full_node.respond_block(RespondBlock(block), None)

        get_hint = await full_node_1.full_node.hint_store.get_coin_ids(hint)

        assert get_hint[0] == Coin(coin_spent.name(), puzzle_hash, uint64(1)).name()

    @pytest.mark.asyncio
    async def test_counts(self, db_version):
        async with DBConnection(db_version) as db_wrapper:
            hint_store = await HintStore.create(db_wrapper)
            count = await hint_store.count_hints()
            assert count == 0

            # Add some hint data then test again
            hint_0 = 32 * b"\0"
            hint_1 = 32 * b"\1"
            coin_id_0 = 32 * b"\4"
            coin_id_1 = 32 * b"\5"
            hints = [(coin_id_0, hint_0), (coin_id_1, hint_1)]
            await hint_store.add_hints(hints)

            count = await hint_store.count_hints()
            assert count == 2

    @pytest.mark.asyncio
    async def test_limits(self, db_version):
        async with DBConnection(db_version) as db_wrapper:
            hint_store = await HintStore.create(db_wrapper)

            # Add 200 coins, all with the same hint
            hint = 32 * b"\0"
            for i in range(200):
                coin_id = (28 * b"\4") + i.to_bytes(4, "big")
                await hint_store.add_hints([(coin_id, hint)])

            count = await hint_store.count_hints()
            assert count == 200

            for limit in [0, 1, 42, 200]:
                assert len(await hint_store.get_coin_ids(hint, max_items=limit)) == limit

            assert len(await hint_store.get_coin_ids(hint, max_items=10000)) == 200
