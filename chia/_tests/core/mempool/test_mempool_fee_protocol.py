from __future__ import annotations

import datetime
from typing import Union

import pytest
from chia_rs.sized_ints import uint64

from chia._tests.core.node_height import node_height_at_least
from chia._tests.util.time_out_assert import time_out_assert
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import RespondFeeEstimates
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.wallet.wallet import Wallet


@pytest.mark.anyio
async def test_protocol_messages(
    simulator_and_wallet: tuple[
        list[Union[FullNodeAPI, FullNodeSimulator]], list[tuple[Wallet, ChiaServer]], BlockTools
    ],
) -> None:
    full_nodes, _wallets, bt = simulator_and_wallet
    a_wallet = bt.get_pool_wallet_tool()
    reward_ph = a_wallet.get_new_puzzlehash()
    blocks = bt.get_consecutive_blocks(
        35,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=reward_ph,
        pool_reward_puzzle_hash=reward_ph,
    )

    full_node_sim: Union[FullNodeAPI, FullNodeSimulator] = full_nodes[0]

    for block in blocks:
        await full_node_sim.full_node.add_block(block)

    await time_out_assert(60, node_height_at_least, True, full_node_sim, blocks[-1].height)

    offset_secs = [60, 120, 300]
    now_unix_secs = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    request_times = [uint64(now_unix_secs + s) for s in offset_secs]
    request: wallet_protocol.RequestFeeEstimates = wallet_protocol.RequestFeeEstimates(request_times)
    estimates = await full_node_sim.request_fee_estimates(request)
    assert estimates is not None
    assert estimates.type == ProtocolMessageTypes.respond_fee_estimates.value
    response: RespondFeeEstimates = wallet_protocol.RespondFeeEstimates.from_bytes(estimates.data)

    # Sanity check the response
    assert len(response.estimates.estimates) == len(request_times)
    assert response.estimates.error is None
