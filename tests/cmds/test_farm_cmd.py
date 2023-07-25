from __future__ import annotations

import re
from typing import Tuple

import pytest
from _pytest.capture import CaptureFixture

from chia.cmds.farm_funcs import summary
from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.full_node.full_node import FullNode
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.time_out_assert import time_out_assert
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_node_api import WalletNodeAPI


@pytest.mark.asyncio
async def test_farm_summary_command(
    capsys: CaptureFixture[str],
    farmer_one_harvester_simulator_wallet: Tuple[
        Service[Harvester, HarvesterAPI],
        Service[Farmer, FarmerAPI],
        Service[FullNode, FullNodeSimulator],
        Service[WalletNode, WalletNodeAPI],
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

    await summary(full_node_rpc_port, wallet_rpc_port, None, farmer_rpc_port, bt.root_path)

    captured = capsys.readouterr()
    match = re.search(r"^.+(Farming status:.+)$", captured.out, re.DOTALL)
    assert match is not None
    lines = match.group(1).split("\n")

    assert lines[0] == "Farming status: Not synced or not connected to peers"
    assert "Total chia farmed:" in lines[1]
    assert "User transaction fees:" in lines[2]
    assert "Block rewards:" in lines[3]
    assert "Last height farmed:" in lines[4]
    assert lines[5] == "Local Harvester"
    assert "e (effective)" in lines[6]
    assert "Plot count for all harvesters:" in lines[7]
    assert "e (effective)" in lines[8]
    assert "Estimated network space:" in lines[9]
    assert "Expected time to win:" in lines[10]
