from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from chia.protocols import farmer_protocol
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.proof_of_space import get_plot_id, passes_plot_filter
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.util.ints import uint8, uint64
from tests.conftest import HarvesterFarmerEnvironment
from tests.core.test_farmer_harvester_rpc import wait_for_plot_sync


@pytest.mark.parametrize(
    argnames=["filter_prefix_bits", "should_pass"], argvalues=[(9, 33), (8, 66), (7, 138), (6, 265), (5, 607)]
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


@pytest.mark.parametrize(argnames=["filter_prefix_bits", "should_pass"], argvalues=[(9, False), (8, True)])
@pytest.mark.asyncio
async def test_filter_prefix_bits_with_farmer_harvester(
    harvester_farmer_environment: HarvesterFarmerEnvironment, filter_prefix_bits: uint8, should_pass: bool
) -> None:
    state_change = None
    state_change_data = None

    def state_changed_callback(change: str, change_data: Optional[Dict[str, Any]]) -> None:
        nonlocal state_change, state_change_data
        state_change = change
        state_change_data = change_data

    def state_has_changed() -> bool:
        return state_change is not None and state_change_data is not None

    farmer_service, _, harvester_service, _, _ = harvester_farmer_environment
    harvester_service._node.state_changed_callback = state_changed_callback
    harvester_id = harvester_service._server.node_id
    farmer_api = farmer_service._api
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
        filter_prefix_bits=filter_prefix_bits,
    )
    passed = False
    await farmer_api.new_signage_point(sp)
    await time_out_assert(5, state_has_changed, True)
    # We're intercepting the harvester's state changes as we're expecting
    # a farming_info one. eligible_plots are what passed the plot filter
    if (
        state_change == "farming_info"
        and state_change_data is not None
        and state_change_data.get("eligible_plots") == 1
    ):
        passed = True
    assert passed == should_pass
