from __future__ import annotations

import random
from typing import List, Tuple

import pytest

from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint64
from chia.wallet.puzzles.clawback.metadata import ClawbackMetadata
from chia.wallet.wallet_node import WalletNode


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_is_recipient(
    simulator_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
    trusted: bool,
    self_hostname: str,
    seeded_random: random.Random,
) -> None:
    full_nodes, wallets, _ = simulator_and_wallet
    full_node_api = full_nodes[0]
    server_1: ChiaServer = full_node_api.full_node.server
    wallet_node, server_2 = wallets[0]
    wallet = wallet_node.wallet_state_manager.main_wallet
    puzhash_1 = await wallet.get_new_puzzlehash()
    puzhash_2 = await wallet.get_new_puzzlehash()
    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
    invalid_data = ClawbackMetadata(uint64(500), bytes32.random(seeded_random), bytes32.random(seeded_random))
    both_data = ClawbackMetadata(uint64(500), puzhash_1, puzhash_2)
    sender_data = ClawbackMetadata(uint64(500), puzhash_1, bytes32.random(seeded_random))
    recipient_data = ClawbackMetadata(uint64(500), bytes32.random(seeded_random), puzhash_2)
    # Test invalid metadata
    has_exception = False
    try:
        await invalid_data.is_recipient(wallet_node.wallet_state_manager.puzzle_store)
    except ValueError:
        has_exception = True
    assert has_exception
    # Test valid metadata
    assert not (await both_data.is_recipient(wallet_node.wallet_state_manager.puzzle_store))
    assert await recipient_data.is_recipient(wallet_node.wallet_state_manager.puzzle_store)
    assert not (await sender_data.is_recipient(wallet_node.wallet_state_manager.puzzle_store))
