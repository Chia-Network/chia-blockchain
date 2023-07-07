from __future__ import annotations

from typing import List, Tuple

import pytest

from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16
from chia.wallet.puzzles.clawback.puzzle_decorator import ClawbackPuzzleDecorator
from chia.wallet.util.puzzle_decorator import PuzzleDecoratorManager
from chia.wallet.wallet_node import WalletNode


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_missing_decorator(
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
    trusted: bool,
    self_hostname: str,
) -> None:
    full_nodes, wallets, _ = simulator_and_wallet
    full_node_api = full_nodes[0]
    server_1: ChiaServer = full_node_api.full_node.server
    wallet_node, server_2 = wallets[0]
    decorator_config = {"clawback_timelock": 3600}
    wallet_node.wallet_state_manager.decorator_manager = PuzzleDecoratorManager.create([decorator_config])
    await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
    assert len(wallet_node.wallet_state_manager.decorator_manager.decorator_list) == 0


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_unknown_decorator(
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
    trusted: bool,
    self_hostname: str,
) -> None:
    full_nodes, wallets, _ = simulator_and_wallet
    full_node_api = full_nodes[0]
    server_1: ChiaServer = full_node_api.full_node.server
    wallet_node, server_2 = wallets[0]
    decorator_config = {"decorator": "UNKNOWN", "clawback_timelock": 3600}
    wallet_node.wallet_state_manager.decorator_manager = PuzzleDecoratorManager.create([decorator_config])
    await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
    assert len(wallet_node.wallet_state_manager.decorator_manager.decorator_list) == 0


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.asyncio
async def test_decorator(
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
    trusted: bool,
    self_hostname: str,
) -> None:
    full_nodes, wallets, _ = simulator_and_wallet
    full_node_api = full_nodes[0]
    server_1: ChiaServer = full_node_api.full_node.server
    wallet_node, server_2 = wallets[0]
    wallet = wallet_node.wallet_state_manager.main_wallet
    print(wallet_node.logged_in_fingerprint)
    decorator_config = {"decorator": "CLAWBACK", "clawback_timelock": 3600}
    wallet_node.wallet_state_manager.decorator_manager = PuzzleDecoratorManager.create([decorator_config])
    await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
    assert len(wallet_node.wallet_state_manager.decorator_manager.decorator_list) == 1
    assert isinstance(wallet_node.wallet_state_manager.decorator_manager.decorator_list[0], ClawbackPuzzleDecorator)
    clawback_decorator: ClawbackPuzzleDecorator = wallet_node.wallet_state_manager.decorator_manager.decorator_list[0]
    assert clawback_decorator.time_lock == 3600
    puzzle = await wallet.get_new_puzzle()
    assert puzzle == wallet_node.wallet_state_manager.decorator_manager.decorate(puzzle)
