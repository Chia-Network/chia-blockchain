from __future__ import annotations

import re

import pytest
from _pytest.capture import CaptureFixture

from chia._tests.util.time_out_assert import time_out_assert
from chia.cmds.farm_funcs import summary
from chia.farmer.farmer import Farmer
from chia.harvester.harvester import Harvester
from chia.server.aliases import FarmerService, HarvesterService, WalletService
from chia.simulator.block_tools import BlockTools
from chia.simulator.start_simulator import SimulatorFullNodeService


@pytest.mark.anyio
async def test_farm_summary_command(
    capsys: CaptureFixture[str],
    farmer_one_harvester_simulator_wallet: tuple[
        HarvesterService,
        FarmerService,
        SimulatorFullNodeService,
        WalletService,
        BlockTools,
    ],
) -> None:
    harvester_service, farmer_service, full_node_service, wallet_service, bt = farmer_one_harvester_simulator_wallet
    harvester: Harvester = harvester_service._node
    farmer: Farmer = farmer_service._node

    async def receiver_available() -> bool:
        return harvester.server.node_id in farmer.plot_sync_receivers

    # Wait for the receiver to show up
    await time_out_assert(20, receiver_available)
    receiver = farmer.plot_sync_receivers[harvester.server.node_id]
    # And wait until the first sync from the harvester to the farmer is done
    await time_out_assert(20, receiver.initial_sync, False)

    assert full_node_service.rpc_server and full_node_service.rpc_server.webserver
    assert wallet_service.rpc_server and wallet_service.rpc_server.webserver
    assert farmer_service.rpc_server and farmer_service.rpc_server.webserver

    full_node_rpc_port = full_node_service.rpc_server.webserver.listen_port
    wallet_rpc_port = wallet_service.rpc_server.webserver.listen_port
    farmer_rpc_port = farmer_service.rpc_server.webserver.listen_port

    await summary(
        rpc_port=full_node_rpc_port,
        wallet_rpc_port=wallet_rpc_port,
        harvester_rpc_port=None,
        farmer_rpc_port=farmer_rpc_port,
        include_pool_rewards=False,
        root_path=bt.root_path,
    )

    captured = capsys.readouterr()
    match = re.search(r"(Farming status:.*)", captured.out, re.DOTALL)
    assert match is not None
    output = match.group(1)

    assert "Farming status:" in output
    assert "Total chia farmed:" in output
    assert "User transaction fees:" in output
    assert "Block rewards:" in output
    assert "Last height farmed:" in output
    assert "Local Harvester" in output
    assert "e (effective)" in output
    assert "Plot count for all harvesters:" in output
    assert "Estimated network space:" in output
    assert "Expected time to win:" in output

    await summary(
        rpc_port=full_node_rpc_port,
        wallet_rpc_port=wallet_rpc_port,
        harvester_rpc_port=None,
        farmer_rpc_port=farmer_rpc_port,
        include_pool_rewards=True,
        root_path=bt.root_path,
    )

    captured = capsys.readouterr()
    match = re.search(r"(Farming status:.*)", captured.out, re.DOTALL)
    assert match is not None
    output = match.group(1)

    assert "Farming status:" in output
    assert "Total chia farmed:" in output
    assert "User transaction fees:" in output
    assert "Farmer rewards:" in output
    assert "Pool rewards:" in output
    assert "Total rewards:" in output
    assert "Local Harvester" in output
    assert "e (effective)" in output
    assert "Plot count for all harvesters:" in output
    assert "Estimated network space:" in output
    assert "Expected time to win:" in output
