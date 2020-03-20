import asyncio
import time

import pytest

from src.types.peer_info import PeerInfo
from src.protocols import full_node_protocol
from src.util.ints import uint16
from tests.setup_nodes import setup_two_nodes, setup_node_and_wallet, test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletSync:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_node_and_wallet():
            yield _

    @pytest.fixture(scope="function")
    async def wallet_node_starting_height(self):
        async for _ in setup_node_and_wallet(dic={"starting_height": 100}):
            yield _

    @pytest.mark.asyncio
    async def test_basic_sync_wallet(self, wallet_node):
        num_blocks = 25
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [])
        full_node_1, wallet_node, server_1, server_2 = wallet_node

        for i in range(1, len(blocks)):
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(blocks[i])
            ):
                pass

        await server_2.start_client(
            PeerInfo(server_1._host, uint16(server_1._port)), None
        )

        start = time.time()
        found = False
        while time.time() - start < 60:
            # The second node should eventually catch up to the first one, and have the
            # same tip at height num_blocks - 1.
            if (
                wallet_node.wallet_state_manager.block_records[
                    wallet_node.wallet_state_manager.lca
                ].height
                >= num_blocks - 6
            ):
                found = True
                break
            await asyncio.sleep(0.1)
        if not found:
            raise Exception(
                f"Took too long to process blocks, stopped at: {time.time() - start}"
            )

        # Tests a reorg with the wallet
        start = time.time()
        found = False
        blocks_reorg = bt.get_consecutive_blocks(test_constants, 45, blocks[:-5])
        for i in range(1, len(blocks_reorg)):
            async for msg in full_node_1.respond_block(
                full_node_protocol.RespondBlock(blocks_reorg[i])
            ):
                server_1.push_message(msg)
        start = time.time()

        while time.time() - start < 100:
            if (
                wallet_node.wallet_state_manager.block_records[
                    wallet_node.wallet_state_manager.lca
                ].height
                == 63
            ):
                found = True
                break
            await asyncio.sleep(0.1)
        if not found:
            raise Exception(
                f"Took too long to process blocks, stopped at: {time.time() - start}"
            )

    @pytest.mark.asyncio
    async def test_fast_sync_wallet(self, wallet_node_starting_height):
        num_blocks = 50
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [])
        full_node_1, wallet_node, server_1, server_2 = wallet_node_starting_height

        for i in range(1, len(blocks)):
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(blocks[i])
            ):
                pass

        await server_2.start_client(
            PeerInfo(server_1._host, uint16(server_1._port)), None
        )

        start = time.time()
        found = False
        while time.time() - start < 60:
            if (
                wallet_node.wallet_state_manager.block_records[
                    wallet_node.wallet_state_manager.lca
                ].height
                >= num_blocks - 6
            ):
                found = True
                break
            await asyncio.sleep(0.1)
        if not found:
            raise Exception(
                f"Took too long to process blocks, stopped at: {time.time() - start}"
            )

    @pytest.mark.asyncio
    async def test_short_sync_wallet(self, wallet_node):
        num_blocks = 8
        blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)
        full_node_1, wallet_node, server_1, server_2 = wallet_node

        for i in range(1, len(blocks)):
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(blocks[i])
            ):
                pass

        await server_2.start_client(
            PeerInfo(server_1._host, uint16(server_1._port)), None
        )
        start = time.time()
        while time.time() - start < 60:
            # The second node should eventually catch up to the first one, and have the
            # same tip at height num_blocks - 1.
            if (
                wallet_node.wallet_state_manager.block_records[
                    wallet_node.wallet_state_manager.lca
                ].height
                == 6
            ):
                return
            await asyncio.sleep(0.1)
        raise Exception(
            f"Took too long to process blocks, stopped at: {time.time() - start}"
        )
