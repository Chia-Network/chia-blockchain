from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, List

import pytest
import pytest_asyncio

from chia.consensus.constants import ConsensusConstants
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import setup_simulators_and_wallets_service
from chia.types.peer_info import PeerInfo
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_state_manager import WalletStateManager


@dataclass
class WalletEnvironment:
    wallet_node: WalletNode
    wallet_state_manager: WalletStateManager
    xch_wallet: Wallet
    rpc_client: WalletRpcClient


@dataclass
class WalletTestFramework:
    full_node: FullNodeSimulator
    trusted_full_node: bool
    environments: List[WalletEnvironment]


@pytest.fixture(scope="function", params=[True, False])
def trusted_full_node(request: Any) -> bool:
    trusted: bool = request.param
    return trusted


@pytest_asyncio.fixture(scope="function")
async def wallet_environments(
    trusted_full_node: bool, request: pytest.FixtureRequest, blockchain_constants: ConsensusConstants
) -> AsyncIterator[WalletTestFramework]:
    async with setup_simulators_and_wallets_service(
        1, request.param["num_environments"], blockchain_constants
    ) as wallet_nodes_services:
        full_node, wallet_services, bt = wallet_nodes_services

        full_node[0]._api.full_node.config = {**full_node[0]._api.full_node.config, **request.param["config_overrides"]}

        rpc_clients: List[WalletRpcClient] = []
        for service in wallet_services:
            service._node.config = {
                **service._node.config,
                "trusted_peers": {full_node[0]._api.server.node_id.hex(): full_node[0]._api.server.node_id.hex()}
                if trusted_full_node
                else {},
                **request.param["config_overrides"],
            }
            service._node.wallet_state_manager.config = service._node.config
            await service._node.server.start_client(
                PeerInfo(bt.config["self_hostname"], full_node[0]._api.full_node.server.get_port()), None
            )
            rpc_clients.append(
                await WalletRpcClient.create(
                    bt.config["self_hostname"],
                    # Semantics guarantee us a non-None value here
                    service.rpc_server.listen_port,  # type: ignore[union-attr]
                    service.root_path,
                    service.config,
                )
            )

        for service, blocks_needed in zip(wallet_services, request.param["blocks_needed"]):
            await full_node[0]._api.farm_blocks_to_wallet(
                count=blocks_needed, wallet=service._node.wallet_state_manager.main_wallet
            )

        yield WalletTestFramework(
            full_node[0]._api,
            trusted_full_node,
            [
                WalletEnvironment(
                    service._node,
                    service._node.wallet_state_manager,
                    service._node.wallet_state_manager.main_wallet,
                    rpc_client,
                )
                for service, rpc_client in zip(wallet_services, rpc_clients)
            ],
        )

        for rpc_client in rpc_clients:
            rpc_client.close()
            await rpc_client.await_closed()
