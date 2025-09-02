from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from chia_rs import ConsensusConstants, FullBlock, ProofOfSpace
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.conftest import HarvesterFarmerEnvironment
from chia._tests.plotting.util import get_test_plots
from chia._tests.util.time_out_assert import time_out_assert
from chia.harvester.harvester_api import HarvesterAPI
from chia.plotting.util import PlotInfo
from chia.protocols import harvester_protocol
from chia.protocols.harvester_protocol import PoolDifficulty
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.ws_connection import WSChiaConnection


@dataclass
class HarvesterTestEnvironment:
    """Test environment with real plots loaded for harvester testing."""

    harvester_api: HarvesterAPI
    plot_info: PlotInfo
    plot_path: Path


@pytest.fixture(scope="function")
async def harvester_environment(
    harvester_farmer_environment: HarvesterFarmerEnvironment,
) -> AsyncGenerator[HarvesterTestEnvironment, None]:
    """Create a test environment with real plots loaded."""
    _, _, harvester_service, _, _ = harvester_farmer_environment
    harvester_api = harvester_service._server.api
    assert isinstance(harvester_api, HarvesterAPI)
    test_plots = get_test_plots()
    assert len(test_plots) > 0, "no test plots available"
    plot_manager = harvester_api.harvester.plot_manager
    plot_manager.start_refreshing()
    await time_out_assert(10, lambda: len(plot_manager.plots) > 0, True)
    plot_path, plot_info = next(iter(plot_manager.plots.items()))
    yield HarvesterTestEnvironment(harvester_api, plot_info, plot_path)
    plot_manager.stop_refreshing()


def signage_point_from_block(
    block: FullBlock, constants: ConsensusConstants
) -> harvester_protocol.NewSignagePointHarvester:
    sp_index = block.reward_chain_block.signage_point_index
    challenge_hash = block.reward_chain_block.pos_ss_cc_challenge_hash
    sp_hash = (
        block.reward_chain_block.reward_chain_sp_vdf.output.get_hash()
        if block.reward_chain_block.reward_chain_sp_vdf
        else challenge_hash
    )
    return harvester_protocol.NewSignagePointHarvester(
        challenge_hash=challenge_hash,
        difficulty=uint64(constants.DIFFICULTY_STARTING),
        sub_slot_iters=uint64(constants.SUB_SLOT_ITERS_STARTING),
        signage_point_index=sp_index,
        sp_hash=sp_hash,
        pool_difficulties=[],
        peak_height=block.height,
        last_tx_height=block.height,
    )


def create_test_setup(
    harvester_environment: HarvesterTestEnvironment,
    default_400_blocks: list[FullBlock],
    blockchain_constants: ConsensusConstants,
) -> tuple[HarvesterTestEnvironment, harvester_protocol.NewSignagePointHarvester, MagicMock]:
    env = harvester_environment
    block = default_400_blocks[2]
    new_challenge = signage_point_from_block(block, blockchain_constants)
    mock_peer = MagicMock(spec=WSChiaConnection)
    return env, new_challenge, mock_peer


@contextmanager
def mock_successful_proof(plot_info: PlotInfo) -> Iterator[None]:
    with patch.object(plot_info.prover, "get_full_proof") as mock_get_proof:
        mock_proof = MagicMock(spec=ProofOfSpace)
        mock_get_proof.return_value = mock_proof, None
        yield


def assert_farming_info_sent(mock_peer: MagicMock) -> None:
    mock_peer.send_message.assert_called()
    farming_info_calls = [
        call
        for call in mock_peer.send_message.call_args_list
        if call[0][0].type == ProtocolMessageTypes.farming_info.value
    ]
    assert len(farming_info_calls) == 1


@pytest.mark.anyio
async def test_new_signage_point_harvester(
    harvester_environment: HarvesterTestEnvironment,
    default_400_blocks: list[FullBlock],
    blockchain_constants: ConsensusConstants,
) -> None:
    env, new_challenge, mock_peer = create_test_setup(harvester_environment, default_400_blocks, blockchain_constants)
    with mock_successful_proof(env.plot_info):
        await env.harvester_api.new_signage_point_harvester(new_challenge, mock_peer)
    assert_farming_info_sent(mock_peer)


@pytest.mark.anyio
async def test_new_signage_point_harvester_pool_difficulty(
    harvester_environment: HarvesterTestEnvironment,
    default_400_blocks: list[FullBlock],
    blockchain_constants: ConsensusConstants,
) -> None:
    env, new_challenge, mock_peer = create_test_setup(harvester_environment, default_400_blocks, blockchain_constants)
    pool_puzzle_hash = bytes32(b"pool" + b"0" * 28)
    env.plot_info.pool_contract_puzzle_hash = pool_puzzle_hash
    pool_difficulty = PoolDifficulty(
        pool_contract_puzzle_hash=pool_puzzle_hash,
        difficulty=uint64(500),
        sub_slot_iters=uint64(67108864),
    )

    new_challenge = harvester_protocol.NewSignagePointHarvester(
        challenge_hash=new_challenge.challenge_hash,
        difficulty=new_challenge.difficulty,
        sub_slot_iters=new_challenge.sub_slot_iters,
        signage_point_index=new_challenge.signage_point_index,
        sp_hash=new_challenge.sp_hash,
        pool_difficulties=[pool_difficulty],  # add pool difficulty
        peak_height=new_challenge.peak_height,
        last_tx_height=new_challenge.last_tx_height,
    )

    with mock_successful_proof(env.plot_info):
        await env.harvester_api.new_signage_point_harvester(new_challenge, mock_peer)

    assert_farming_info_sent(mock_peer)


@pytest.mark.anyio
async def test_new_signage_point_harvester_prover_error(
    harvester_environment: HarvesterTestEnvironment,
    default_400_blocks: list[FullBlock],
    blockchain_constants: ConsensusConstants,
) -> None:
    env, new_challenge, mock_peer = create_test_setup(harvester_environment, default_400_blocks, blockchain_constants)
    with patch.object(env.plot_info.prover, "get_qualities_for_challenge", side_effect=RuntimeError("test error")):
        # should not raise exception, should handle error gracefully
        await env.harvester_api.new_signage_point_harvester(new_challenge, mock_peer)
