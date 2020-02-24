import asyncio

import pytest
from blspy import ExtendedPrivateKey

from src.protocols.wallet_protocol import RespondBody
from src.wallet.wallet import Wallet
from tests.setup_nodes import setup_two_nodes, test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWallet:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes({"COINBASE_FREEZE_PERIOD": 0}):
            yield _

    @pytest.mark.asyncio
    async def test_wallet_receive_body(self, two_nodes):
        sk = bytes(ExtendedPrivateKey.from_seed(b"")).hex()
        key_config = {"wallet_sk": sk}

        wallet = await Wallet.create({}, key_config)
        await wallet.wallet_store._clear_database()

        num_blocks = 10
        blocks = bt.get_consecutive_blocks(
            test_constants,
            num_blocks,
            [],
            10,
            reward_puzzlehash=wallet.get_new_puzzlehash(),
        )

        for i in range(1, num_blocks):
            a = RespondBody(blocks[i].body, blocks[i].height)
            await wallet.received_body(a)

        assert await wallet.get_confirmed_balance() == 144000000000000

        await wallet.wallet_store.close()

    @pytest.mark.asyncio
    async def test_wallet_make_transaction(self, two_nodes):
        sk = bytes(ExtendedPrivateKey.from_seed(b"")).hex()
        sk_b = bytes(ExtendedPrivateKey.from_seed(b"b")).hex()
        key_config = {"wallet_sk": sk}
        key_config_b = {"wallet_sk": sk_b}

        wallet = await Wallet.create({}, key_config)
        await wallet.wallet_store._clear_database()
        wallet_b = await Wallet.create({}, key_config_b)
        await wallet_b.wallet_store._clear_database()

        num_blocks = 10
        blocks = bt.get_consecutive_blocks(
            test_constants,
            num_blocks,
            [],
            10,
            reward_puzzlehash=wallet.get_new_puzzlehash(),
        )

        for i in range(1, num_blocks):
            a = RespondBody(blocks[i].body, blocks[i].height)
            await wallet.received_body(a)

        assert await wallet.get_confirmed_balance() == 144000000000000

        spend_bundle = await wallet.generate_signed_transaction(
            10, wallet_b.get_new_puzzlehash(), 0
        )
        await wallet.push_transaction(spend_bundle)

        confirmed_balance = await wallet.get_confirmed_balance()
        unconfirmed_balance = await wallet.get_unconfirmed_balance()

        assert confirmed_balance == 144000000000000
        assert unconfirmed_balance == confirmed_balance - 10

        await wallet.wallet_store.close()
        await wallet_b.wallet_store.close()
