import asyncio
import signal
import time
from os import urandom

import pytest
from blspy import ExtendedPrivateKey

from src.protocols.wallet_protocol import RespondBody
from src.protocols import full_node_protocol
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
        self.seed = urandom(1024)
        sk = bytes(ExtendedPrivateKey.from_seed(b"")).hex()
        key_config = {"wallet_sk": sk}

        wallet = await Wallet.create({}, key_config)

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
