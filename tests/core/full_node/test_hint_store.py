import asyncio
import logging
import pytest
from clvm.casts import int_to_bytes

from chia.consensus.blockchain import Blockchain
from chia.full_node.hint_store import HintStore
from chia.types.blockchain_format.coin import Coin
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.spend_bundle import SpendBundle
from tests.blockchain.blockchain_test_utils import _validate_and_add_block, _validate_and_add_block_no_error
from tests.util.db_connection import DBConnection
from tests.wallet_tools import WalletTool
from tests.setup_nodes import bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


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
            await db_wrapper.commit_transaction()
            coins_for_hint_0 = await hint_store.get_coin_ids(hint_0)

            assert coin_id_0 in coins_for_hint_0
            assert coin_id_1 in coins_for_hint_0

            coins_for_hint_1 = await hint_store.get_coin_ids(hint_1)
            assert coin_id_2 in coins_for_hint_1

            coins_for_non_hint = await hint_store.get_coin_ids(not_existing_hint)
            assert coins_for_non_hint == []

    async def test_duplicate_coins(self, db_version):
        async with DBConnection(db_version) as db_wrapper:
            hint_store = await HintStore.create(db_wrapper)
            hint_0 = 32 * b"\0"
            hint_1 = 32 * b"\1"

            coin_id_0 = 32 * b"\4"

            hints = [(coin_id_0, hint_0), (coin_id_0, hint_1)]
            await hint_store.add_hints(hints)
            await db_wrapper.commit_transaction()
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
            await db_wrapper.commit_transaction()
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
                await db_wrapper.commit_transaction()
            coins_for_hint_0 = await hint_store.get_coin_ids(hint_0)
            assert coin_id_0 in coins_for_hint_0

            cursor = await db_wrapper.db.execute("SELECT COUNT(*) FROM hints")
            rows = await cursor.fetchall()

            if db_wrapper.db_version == 2:
                # even though we inserted the pair multiple times, there's only one
                # entry in the DB
                assert rows[0][0] == 1
            else:
                # we get one copy for each duplicate
                assert rows[0][0] == 4

    @pytest.mark.asyncio
    async def test_hints_in_blockchain(self, empty_blockchain):  # noqa: F811
        blockchain: Blockchain = empty_blockchain

        blocks = bt.get_consecutive_blocks(
            5,
            block_list_input=[],
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        for block in blocks:
            await _validate_and_add_block(blockchain, block)

        wt: WalletTool = bt.get_pool_wallet_tool()
        puzzle_hash = 32 * b"\0"
        amount = int_to_bytes(1)
        hint = 32 * b"\5"
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

        for block in blocks:
            await _validate_and_add_block_no_error(blockchain, block)

        get_hint = await blockchain.hint_store.get_coin_ids(hint)

        assert get_hint[0] == Coin(coin_spent.name(), puzzle_hash, 1).name()

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
            await db_wrapper.commit_transaction()

            count = await hint_store.count_hints()
            assert count == 2
