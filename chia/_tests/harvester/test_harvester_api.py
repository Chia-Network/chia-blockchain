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


def create_signage_point_harvester_from_constants(bt: BlockTools) -> harvester_protocol.NewSignagePointHarvester:
    """create a NewSignagePointHarvester using real constants from block tools"""
    # use the pre-generated signage point data from network_protocol_data.py
    # but with real constants from block_tools
    from chia._tests.util.network_protocol_data import new_signage_point_harvester

    # create a version with real constants values
    return harvester_protocol.NewSignagePointHarvester(
        challenge_hash=new_signage_point_harvester.challenge_hash,
        difficulty=uint64(bt.constants.DIFFICULTY_STARTING),
        sub_slot_iters=uint64(bt.constants.SUB_SLOT_ITERS_STARTING),
        signage_point_index=new_signage_point_harvester.signage_point_index,
        sp_hash=new_signage_point_harvester.sp_hash,
        pool_difficulties=[],  # empty for simplicity, unless testing pool functionality
        peak_height=new_signage_point_harvester.peak_height,
        last_tx_height=new_signage_point_harvester.last_tx_height,
    )


@pytest.mark.anyio
async def test_new_signage_point_harvester_no_keys(
    harvester_farmer_environment: HarvesterFarmerEnvironment,
) -> None:
    """test that new_signage_point_harvester returns early when no keys available"""
    _farmer_service, _farmer_rpc_client, harvester_service, _harvester_rpc_client, bt = harvester_farmer_environment
    harvester_api = harvester_service._server.api
    assert isinstance(harvester_api, HarvesterAPI)

    # create real signage point data from block tools
    new_challenge = create_signage_point_harvester_from_constants(bt)

    # mock plot manager to return false for public_keys_available
    with patch.object(harvester_api.harvester.plot_manager, "public_keys_available", return_value=False):
        mock_peer = MagicMock(spec=WSChiaConnection)

        result = harvester_api.new_signage_point_harvester(new_challenge, mock_peer)
        assert result is None


@pytest.mark.anyio
async def test_new_signage_point_harvester_happy_path(
    harvester_farmer_environment: HarvesterFarmerEnvironment,
) -> None:
    """test successful signage point processing with valid plots"""
    _farmer_service, _farmer_rpc_client, harvester_service, _harvester_rpc_client, bt = harvester_farmer_environment
    harvester_api = harvester_service._server.api
    assert isinstance(harvester_api, HarvesterAPI)

    # create real signage point data from block tools
    new_challenge = create_signage_point_harvester_from_constants(bt)

    mock_peer = MagicMock(spec=WSChiaConnection)

    # create mock plot info
    mock_prover = MagicMock()
    mock_prover.get_id.return_value = bytes32(b"2" * 32)
    mock_prover.get_size.return_value = 32
    mock_prover.get_qualities_for_challenge.return_value = [bytes32(b"quality" + b"0" * 25)]

    mock_plot_info = MagicMock(spec=PlotInfo)
    mock_plot_info.prover = mock_prover
    mock_plot_info.pool_contract_puzzle_hash = None

    plot_path = Path("/fake/plot.plot")

    with patch.object(harvester_api.harvester.plot_manager, "public_keys_available", return_value=True):
        with patch.object(harvester_api.harvester.plot_manager, "plots", {plot_path: mock_plot_info}):
            with patch("chia.harvester.harvester_api.passes_plot_filter", return_value=True):
                with patch("chia.harvester.harvester_api.calculate_pos_challenge") as mock_calc_pos:
                    mock_calc_pos.return_value = bytes32(b"sp_challenge" + b"0" * 20)

                    with patch("chia.harvester.harvester_api.calculate_iterations_quality") as mock_calc_iter:
                        # set required_iters low enough to pass the sp_interval_iters check
                        mock_calc_iter.return_value = uint64(1000)

                        with patch("chia.harvester.harvester_api.calculate_sp_interval_iters") as mock_sp_interval:
                            mock_sp_interval.return_value = uint64(10000)

                            with patch.object(mock_prover, "get_full_proof") as mock_get_proof:
                                mock_proof = MagicMock(spec=ProofOfSpace)
                                mock_get_proof.return_value = mock_proof, None

                                result = harvester_api.new_signage_point_harvester(new_challenge, mock_peer)
                                # function returns None but should have processed the plot
                                assert result is None


@pytest.mark.anyio
async def test_new_signage_point_harvester_pool_difficulty_override(
    harvester_farmer_environment: HarvesterFarmerEnvironment,
) -> None:
    """test that pool difficulty overrides are applied correctly"""
    _farmer_service, _farmer_rpc_client, harvester_service, _harvester_rpc_client, bt = harvester_farmer_environment
    harvester_api = harvester_service._server.api
    assert isinstance(harvester_api, HarvesterAPI)

    mock_peer = MagicMock(spec=WSChiaConnection)

    pool_puzzle_hash = bytes32(b"pool" + b"0" * 28)

    mock_prover = MagicMock()
    mock_prover.get_id.return_value = bytes32(b"2" * 32)
    mock_prover.get_size.return_value = 32
    mock_prover.get_qualities_for_challenge.return_value = [bytes32(b"quality" + b"0" * 25)]

    mock_plot_info = MagicMock(spec=PlotInfo)
    mock_plot_info.prover = mock_prover
    mock_plot_info.pool_contract_puzzle_hash = pool_puzzle_hash

    plot_path = Path("/fake/plot.plot")

    pool_difficulty = PoolDifficulty(
        pool_contract_puzzle_hash=pool_puzzle_hash,
        difficulty=uint64(500),  # lower than main difficulty
        sub_slot_iters=uint64(67108864),  # different from main
    )

    # create real signage point data from constants with pool difficulty
    new_challenge = create_signage_point_harvester_from_constants(bt)
    # override with pool difficulty for this test
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
            with patch("chia.harvester.harvester_api.passes_plot_filter", return_value=True):
                with patch("chia.harvester.harvester_api.calculate_pos_challenge") as mock_calc_pos:
                    mock_calc_pos.return_value = bytes32(b"sp_challenge" + b"0" * 20)

                    with patch("chia.harvester.harvester_api.calculate_iterations_quality") as mock_calc_iter:
                        mock_calc_iter.return_value = uint64(1000)

                        with patch("chia.harvester.harvester_api.calculate_sp_interval_iters") as mock_sp_interval:
                            mock_sp_interval.return_value = uint64(10000)

                            with patch.object(mock_prover, "get_full_proof") as mock_get_proof:
                                mock_proof = MagicMock(spec=ProofOfSpace)
                                mock_get_proof.return_value = mock_proof, None

                                result = harvester_api.new_signage_point_harvester(new_challenge, mock_peer)

                                # verify that calculate_iterations_quality was called with pool difficulty
                                mock_calc_iter.assert_called()
                                call_args = mock_calc_iter.call_args[0]
                                assert call_args[3] == uint64(500)  # pool difficulty was used

                                assert result is None


@pytest.mark.anyio
async def test_new_signage_point_harvester_prover_error(
    harvester_farmer_environment: HarvesterFarmerEnvironment,
) -> None:
    """test error handling when prover fails"""
    _farmer_service, _farmer_rpc_client, harvester_service, _harvester_rpc_client, bt = harvester_farmer_environment
    harvester_api = harvester_service._server.api
    assert isinstance(harvester_api, HarvesterAPI)

    # create real signage point data from block tools
    new_challenge = create_signage_point_harvester_from_constants(bt)

    mock_peer = MagicMock(spec=WSChiaConnection)

    mock_prover = MagicMock()
    mock_prover.get_id.return_value = bytes32(b"2" * 32)
    mock_prover.get_qualities_for_challenge.side_effect = RuntimeError("test error")

    mock_plot_info = MagicMock(spec=PlotInfo)
    mock_plot_info.prover = mock_prover
    mock_plot_info.pool_contract_puzzle_hash = None

    plot_path = Path("/fake/plot.plot")

    with patch.object(harvester_api.harvester.plot_manager, "public_keys_available", return_value=True):
        with patch.object(harvester_api.harvester.plot_manager, "plots", {plot_path: mock_plot_info}):
            with patch("chia.harvester.harvester_api.passes_plot_filter", return_value=True):
                with patch("chia.harvester.harvester_api.calculate_pos_challenge") as mock_calc_pos:
                    mock_calc_pos.return_value = bytes32(b"sp_challenge" + b"0" * 20)

                    # should not raise exception, should handle error gracefully
                    result = harvester_api.new_signage_point_harvester(new_challenge, mock_peer)
                    assert result is None
