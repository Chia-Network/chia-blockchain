from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from chia_rs import ProofOfSpace
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.conftest import HarvesterFarmerEnvironment
from chia.harvester.harvester_api import HarvesterAPI
from chia.plotting.util import PlotInfo
from chia.protocols import harvester_protocol
from chia.protocols.harvester_protocol import PoolDifficulty
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.block_tools import BlockTools


def signage_point_from_block(bt: BlockTools) -> harvester_protocol.NewSignagePointHarvester:
    """Create a real NewSignagePointHarvester from actual blockchain blocks."""
    # generate real blocks using BlockTools
    blocks = bt.get_consecutive_blocks(
        num_blocks=3,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=bt.farmer_ph,
    )
    block = blocks[-1]  # always use the last block
    # extract real signage point data from the block
    sp_index = block.reward_chain_block.signage_point_index
    challenge_hash = block.reward_chain_block.pos_ss_cc_challenge_hash
    sp_hash = (
        block.reward_chain_block.reward_chain_sp_vdf.output.get_hash()
        if block.reward_chain_block.reward_chain_sp_vdf
        else challenge_hash
    )

    return harvester_protocol.NewSignagePointHarvester(
        challenge_hash=challenge_hash,
        difficulty=uint64(bt.constants.DIFFICULTY_STARTING),
        sub_slot_iters=uint64(bt.constants.SUB_SLOT_ITERS_STARTING),
        signage_point_index=sp_index,
        sp_hash=sp_hash,
        pool_difficulties=[],
        peak_height=block.height,
        last_tx_height=block.height,
    )


def create_plot_info() -> PlotInfo:
    """Create a realistic PlotInfo mock for testing."""
    mock_prover = MagicMock()
    mock_prover.get_id.return_value = bytes32(b"plot_id_123456789012345678901234")  # exactly 32 bytes
    mock_prover.get_size.return_value = 32  # standard k32 plot
    mock_prover.get_qualities_for_challenge.return_value = [
        bytes32(b"quality_123456789012345678901234")
    ]  # exactly 32 bytes
    mock_plot_info = MagicMock(spec=PlotInfo)
    mock_plot_info.prover = mock_prover
    mock_plot_info.pool_contract_puzzle_hash = None

    return mock_plot_info


@pytest.mark.anyio
async def test_new_signage_point_harvester(harvester_farmer_environment: HarvesterFarmerEnvironment) -> None:
    """Test successful signage point processing with real blockchain data."""
    _, _, harvester_service, _, bt = harvester_farmer_environment
    harvester_api = harvester_service._server.api
    assert isinstance(harvester_api, HarvesterAPI)
    # use real signage point data from actual block
    new_challenge = signage_point_from_block(bt)
    # harvester doesn't accept incoming connections, so use mock peer like other tests
    mock_peer = MagicMock(spec=WSChiaConnection)
    # create realistic plot info for testing
    mock_plot_info = create_plot_info()
    plot_path = Path("/fake/plot.plot")

    with patch.object(harvester_api.harvester.plot_manager, "public_keys_available", return_value=True):
        with patch.object(harvester_api.harvester.plot_manager, "plots", {plot_path: mock_plot_info}):
            # let passes_plot_filter, calculate_pos_challenge, and calculate_sp_interval_iters use real implementations
            with patch("chia.harvester.harvester_api.calculate_iterations_quality", return_value=uint64(1000)):
                with patch.object(mock_plot_info.prover, "get_full_proof") as mock_get_proof:
                    mock_proof = MagicMock(spec=ProofOfSpace)
                    mock_get_proof.return_value = mock_proof, None
                    await harvester_api.new_signage_point_harvester(new_challenge, mock_peer)


@pytest.mark.anyio
async def test_new_signage_point_harvester_pool_difficulty(
    harvester_farmer_environment: HarvesterFarmerEnvironment,
) -> None:
    """Test pool difficulty overrides with real blockchain signage points."""
    _, _, harvester_service, _, bt = harvester_farmer_environment
    harvester_api = harvester_service._server.api
    assert isinstance(harvester_api, HarvesterAPI)

    # harvester doesn't accept incoming connections, so use mock peer like other tests
    mock_peer = MagicMock(spec=WSChiaConnection)
    pool_puzzle_hash = bytes32(b"pool" + b"0" * 28)

    # create realistic plot info for testing
    mock_plot_info = create_plot_info()
    mock_plot_info.pool_contract_puzzle_hash = pool_puzzle_hash
    plot_path = Path("/fake/pool_plot.plot")
    pool_difficulty = PoolDifficulty(
        pool_contract_puzzle_hash=pool_puzzle_hash,
        difficulty=uint64(500),  # lower than main difficulty
        sub_slot_iters=uint64(67108864),  # different from main
    )

    # create signage point from real block with pool difficulty
    new_challenge = signage_point_from_block(bt)
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

    with patch.object(harvester_api.harvester.plot_manager, "public_keys_available", return_value=True):
        with patch.object(harvester_api.harvester.plot_manager, "plots", {plot_path: mock_plot_info}):
            # mock passes_plot_filter to return True so we can test pool difficulty logic
            with patch("chia.harvester.harvester_api.passes_plot_filter", return_value=True):
                with patch("chia.harvester.harvester_api.calculate_iterations_quality") as mock_calc_iter:
                    mock_calc_iter.return_value = uint64(1000)
                    with patch.object(mock_plot_info.prover, "get_full_proof") as mock_get_proof:
                        mock_proof = MagicMock(spec=ProofOfSpace)
                        mock_get_proof.return_value = mock_proof, None
                        await harvester_api.new_signage_point_harvester(new_challenge, mock_peer)
                        # verify that calculate_iterations_quality was called with pool difficulty
                        mock_calc_iter.assert_called()
                        call_args = mock_calc_iter.call_args[0]
                        assert call_args[3] == uint64(500)  # pool difficulty was used


@pytest.mark.anyio
async def test_new_signage_point_harvester_prover_error(
    harvester_farmer_environment: HarvesterFarmerEnvironment,
) -> None:
    """Test error handling when prover fails using real blockchain data."""
    _, _, harvester_service, _, bt = harvester_farmer_environment
    harvester_api = harvester_service._server.api
    assert isinstance(harvester_api, HarvesterAPI)

    # create signage point from real block
    new_challenge = signage_point_from_block(bt)

    mock_peer = MagicMock(spec=WSChiaConnection)

    # create realistic plot info for testing
    mock_plot_info = create_plot_info()
    plot_path = Path("/fake/plot.plot")

    with patch.object(harvester_api.harvester.plot_manager, "public_keys_available", return_value=True):
        with patch.object(harvester_api.harvester.plot_manager, "plots", {plot_path: mock_plot_info}):
            # let passes_plot_filter and calculate_pos_challenge use real implementations
            # make the prover fail during quality check
            with patch.object(
                mock_plot_info.prover, "get_qualities_for_challenge", side_effect=RuntimeError("test error")
            ):
                # should not raise exception, should handle error gracefully
                await harvester_api.new_signage_point_harvester(new_challenge, mock_peer)
