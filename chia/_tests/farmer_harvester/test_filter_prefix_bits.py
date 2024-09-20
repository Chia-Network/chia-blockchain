from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import pytest

from chia._tests.conftest import ConsensusMode
from chia._tests.core.test_farmer_harvester_rpc import wait_for_plot_sync
from chia._tests.util.setup_nodes import setup_farmer_multi_harvester
from chia._tests.util.time_out_assert import time_out_assert
from chia.farmer.farmer_api import FarmerAPI
from chia.protocols import farmer_protocol
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.simulator.block_tools import create_block_tools_async, test_constants
from chia.types.aliases import HarvesterService
from chia.types.blockchain_format.proof_of_space import get_plot_id, passes_plot_filter
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.util.ints import uint8, uint32, uint64
from chia.util.keychain import Keychain


# these numbers are only valid for chains farmed with the fixed original plot
# filter. The HARD_FORK_2_0 consensus mode uses a chain where blocks are farmed
# with wider filters. i.e. some valid blocks may still not pass the filter in
# this test
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
@pytest.mark.parametrize(
    argnames=["filter_prefix_bits", "should_pass"], argvalues=[(9, 34), (8, 89), (7, 162), (6, 295), (5, 579)]
)
def test_filter_prefix_bits_on_blocks(
    default_10000_blocks: List[FullBlock], filter_prefix_bits: uint8, should_pass: int
) -> None:
    passed = 0
    for block in default_10000_blocks:
        plot_id = get_plot_id(block.reward_chain_block.proof_of_space)
        original_challenge_hash = block.reward_chain_block.pos_ss_cc_challenge_hash
        if block.reward_chain_block.challenge_chain_sp_vdf is None:
            assert block.reward_chain_block.signage_point_index == 0
            signage_point = original_challenge_hash
        else:
            signage_point = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
        if passes_plot_filter(filter_prefix_bits, plot_id, original_challenge_hash, signage_point):
            passed += 1
    assert passed == should_pass


@pytest.fixture(scope="function")
async def farmer_harvester_with_filter_size_9(
    get_temp_keyring: Keychain, tmp_path: Path, self_hostname: str
) -> AsyncIterator[Tuple[HarvesterService, FarmerAPI]]:
    async def have_connections() -> bool:
        return len(await farmer_rpc_cl.get_connections()) > 0

    local_b_tools = await create_block_tools_async(
        constants=test_constants.replace(NUMBER_ZERO_BITS_PLOT_FILTER=uint8(9)), keychain=get_temp_keyring
    )
    new_config = local_b_tools._config
    local_b_tools.change_config(new_config)
    async with setup_farmer_multi_harvester(
        local_b_tools, 1, tmp_path, local_b_tools.constants, start_services=True
    ) as (harvesters, farmer_service, _):
        harvester_service = harvesters[0]
        assert farmer_service.rpc_server is not None
        farmer_rpc_cl = await FarmerRpcClient.create(
            self_hostname, farmer_service.rpc_server.listen_port, farmer_service.root_path, farmer_service.config
        )
        assert harvester_service.rpc_server is not None
        harvester_rpc_cl = await HarvesterRpcClient.create(
            self_hostname,
            harvester_service.rpc_server.listen_port,
            harvester_service.root_path,
            harvester_service.config,
        )
        await time_out_assert(15, have_connections, True)
        yield harvester_service, farmer_service._api

    farmer_rpc_cl.close()
    harvester_rpc_cl.close()
    await farmer_rpc_cl.await_closed()
    await harvester_rpc_cl.await_closed()


@pytest.mark.parametrize(argnames=["peak_height", "eligible_plots"], argvalues=[(5495999, 0), (5496000, 1)])
@pytest.mark.anyio
async def test_filter_prefix_bits_with_farmer_harvester(
    farmer_harvester_with_filter_size_9: Tuple[HarvesterService, FarmerAPI],
    peak_height: uint32,
    eligible_plots: int,
) -> None:
    state_change = None
    state_change_data = None

    def state_changed_callback(change: str, change_data: Optional[Dict[str, Any]]) -> None:
        nonlocal state_change, state_change_data
        state_change = change
        state_change_data = change_data

    def state_has_changed() -> bool:
        return state_change is not None and state_change_data is not None

    # We need a custom block tools with constants that set the initial filter
    # size to 9 in order to test peak heights that cover sizes 9 and 8 respectively
    harvester_service, farmer_api = farmer_harvester_with_filter_size_9
    harvester_service._node.state_changed_callback = state_changed_callback
    harvester_id = harvester_service._server.node_id
    receiver = farmer_api.farmer.plot_sync_receivers[harvester_id]
    if receiver.initial_sync():
        await wait_for_plot_sync(receiver, receiver.last_sync().sync_id)
    # This allows us to pass the plot filter with prefix bits 8 but not 9
    challenge_hash = bytes32.from_hexstr("0x73490e166d0b88347c37d921660b216c27316aae9a3450933d3ff3b854e5831a")
    sp_hash = bytes32.from_hexstr("0x7b3e23dbd438f9aceefa9827e2c5538898189987f49b06eceb7a43067e77b531")
    sp = farmer_protocol.NewSignagePoint(
        challenge_hash=challenge_hash,
        challenge_chain_sp=sp_hash,
        reward_chain_sp=bytes32(b"1" * 32),
        difficulty=uint64(1),
        sub_slot_iters=uint64(1000000),
        signage_point_index=uint8(2),
        peak_height=peak_height,
    )
    await farmer_api.new_signage_point(sp)
    await time_out_assert(5, state_has_changed, True)
    # We're intercepting the harvester's state changes as we're expecting
    # a farming_info one.
    assert state_change == "farming_info"
    assert state_change_data is not None
    assert state_change_data.get("eligible_plots") == eligible_plots
