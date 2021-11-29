import asyncio
import pytest
from chia.protocols import full_node_protocol, wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from tests.core.node_height import node_height_at_least
from tests.setup_nodes import bt, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="module")
async def full_node():
    async_gen = setup_simulators_and_wallets(1, 1, {})
    nodes, _ = await async_gen.__anext__()
    full_node_1 = nodes[0]
    server_1 = full_node_1.full_node.server
    yield full_node_1, server_1

    async for _ in async_gen:
        yield _


class TestEstimatesProtocol:
    @pytest.mark.asyncio
    async def test_protocol_messages(self, full_node):
        WALLET_A = bt.get_pool_wallet_tool()
        reward_ph = WALLET_A.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            35,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node, server = full_node

        for block in blocks:
            await full_node.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node, blocks[-1].height)

        request: wallet_protocol.RequestFeeEstimates = wallet_protocol.RequestFeeEstimates(0)
        estimates = await full_node.request_fee_estimates(request)
        assert estimates.type == ProtocolMessageTypes.respond_fee_estimates.value
        response = wallet_protocol.RespondFeeEstimates.from_bytes(estimates.data)

        # Sanity check
        assert float(response.estimates.short) == 0
        assert float(response.estimates.medium) == 0
        assert float(response.estimates.long) == 0
