from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest
from chia_rs import ConsensusConstants, FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia.consensus.blockchain import Blockchain
from chia.consensus.get_block_challenge import get_block_challenge
from chia.consensus.pot_iterations import is_overflow_block
from chia.protocols.solver_protocol import SolverInfo
from chia.simulator.setup_services import setup_solver
from chia.solver.solver_rpc_client import SolverRpcClient
from chia.types.blockchain_format.proof_of_space import verify_and_get_quality_string


@pytest.mark.anyio
async def test_solver_api_methods(blockchain_constants: ConsensusConstants, tmp_path: Path) -> None:
    async with setup_solver(tmp_path, blockchain_constants) as solver_service:
        solver = solver_service._node
        solver_api = solver_service._api
        assert solver_api.ready() is True

        # test solve with real SolverInfo
        test_info = SolverInfo(plot_size=uint8(32), plot_diffculty=uint64(1500), quality_string=bytes32([42] * 32))

        # test normal solve operation (stub returns None)
        result = solver.solve(test_info)
        assert result is None

        # test with mocked return value to verify full flow
        expected_proof = b"test_proof_data_12345"
        with patch.object(solver, "solve", return_value=expected_proof):
            api_result = await solver_api.solve(test_info)
            assert api_result is not None
            # api returns protocol message for peer communication
            from chia.protocols.outbound_message import Message

            assert isinstance(api_result, Message)

        # test error handling - solver not started
        original_started = solver.started
        solver.started = False
        api_result = await solver_api.solve(test_info)
        assert api_result is None
        solver.started = original_started


@pytest.mark.anyio
async def test_solver_with_real_blocks_and_signage_points(
    blockchain_constants: ConsensusConstants,
    default_400_blocks: list[FullBlock],
    empty_blockchain: Blockchain,
    self_hostname: str,
    tmp_path: Path,
) -> None:
    blockchain = empty_blockchain
    blocks = default_400_blocks[:3]
    for block in blocks:
        await _validate_and_add_block(empty_blockchain, block)
    block = blocks[-1]  # always use the last block
    overflow = is_overflow_block(blockchain_constants, block.reward_chain_block.signage_point_index)
    challenge = get_block_challenge(blockchain_constants, block, blockchain, False, overflow, False)
    assert block.reward_chain_block.pos_ss_cc_challenge_hash == challenge
    if block.reward_chain_block.challenge_chain_sp_vdf is None:
        challenge_chain_sp: bytes32 = challenge
    else:
        challenge_chain_sp = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
    # extract real quality data from blocks using chia's proof of space verification
    pos = block.reward_chain_block.proof_of_space
    # calculate real quality string from proof of space data
    quality_string: Optional[bytes32] = verify_and_get_quality_string(
        block.reward_chain_block.proof_of_space,
        blockchain_constants,
        challenge,
        challenge_chain_sp,
        height=block.reward_chain_block.height,
    )

    assert quality_string is not None
    quality_hex = quality_string.hex()

    # test solver with real blockchain quality
    plot_size = pos.size()
    k_size = plot_size.size_v1 if plot_size.size_v1 is not None else plot_size.size_v2
    assert k_size is not None
    async with setup_solver(tmp_path, blockchain_constants) as solver_service:
        assert solver_service.rpc_server is not None
        solver_rpc_client = await SolverRpcClient.create(
            self_hostname, solver_service.rpc_server.listen_port, solver_service.root_path, solver_service.config
        )
        solve_response = await solver_rpc_client.solve(quality_hex, int(k_size), 1000)
        assert solve_response["success"] is True
        assert "proof" in solve_response
        # stub implementation returns None, real implementation would return actual proof
        assert solve_response["proof"] is None


@pytest.mark.anyio
async def test_solver_error_handling_and_edge_cases(
    blockchain_constants: ConsensusConstants, self_hostname: str, tmp_path: Path
) -> None:
    async with setup_solver(tmp_path, blockchain_constants) as solver_service:
        assert solver_service.rpc_server is not None
        solver_rpc_client = await SolverRpcClient.create(
            self_hostname, solver_service.rpc_server.listen_port, solver_service.root_path, solver_service.config
        )

        # test invalid quality string format
        try:
            await solver_rpc_client.solve("invalid_hex")
            assert False, "should have raised exception for invalid hex"
        except Exception:
            pass  # expected

        # test edge case parameters
        valid_quality = "1234567890abcdef" * 4

        # test with edge case plot sizes and difficulties
        edge_cases = [
            (18, 1),  # minimum plot size, minimum difficulty
            (50, 999999),  # large plot size, high difficulty
        ]

        for plot_size, difficulty in edge_cases:
            response = await solver_rpc_client.solve(valid_quality, plot_size, difficulty)
            assert response["success"] is True
            assert "proof" in response

        # test solver handles exception in solve method
        solver = solver_service._node
        test_info = SolverInfo(plot_size=uint8(32), plot_diffculty=uint64(1000), quality_string=bytes32.zeros)

        with patch.object(solver, "solve", side_effect=RuntimeError("test error")):
            # solver api should handle exceptions gracefully
            result = await solver_service._api.solve(test_info)
            assert result is None  # api returns None on error
