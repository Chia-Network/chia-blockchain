from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from chia_rs import ConsensusConstants
from chia_rs.sized_ints import uint64

from chia.protocols.outbound_message import Message
from chia.protocols.solver_protocol import SolverInfo
from chia.simulator.block_tools import create_block_tools_async
from chia.simulator.keyring import TempKeyring
from chia.simulator.setup_services import setup_solver
from chia.solver.solver_rpc_client import SolverRpcClient


@pytest.mark.anyio
async def test_solver_api_methods(blockchain_constants: ConsensusConstants, tmp_path: Path) -> None:
    with TempKeyring(populate=True) as keychain:
        bt = await create_block_tools_async(constants=blockchain_constants, keychain=keychain)
        async with setup_solver(tmp_path, bt, blockchain_constants) as solver_service:
            solver = solver_service._node
            solver_api = solver_service._api
            assert solver_api.ready() is True
            test_info = SolverInfo(plot_strength=uint64(1500), partial_proof=b"test_partial_proof_42")
            expected_proof = b"test_proof_data_12345"
            with patch.object(solver, "solve", return_value=expected_proof):
                api_result = await solver_api.solve(test_info)
                assert api_result is not None
                assert isinstance(api_result, Message)


@pytest.mark.anyio
async def test_solver_error_handling(
    blockchain_constants: ConsensusConstants, self_hostname: str, tmp_path: Path
) -> None:
    with TempKeyring(populate=True) as keychain:
        bt = await create_block_tools_async(constants=blockchain_constants, keychain=keychain)
        async with setup_solver(tmp_path, bt, blockchain_constants) as solver_service:
            assert solver_service.rpc_server is not None
            solver_rpc_client = await SolverRpcClient.create(
                self_hostname, solver_service.rpc_server.listen_port, solver_service.root_path, solver_service.config
            )
            try:
                await solver_rpc_client.solve("invalid_hex")
                assert False, "should have raised exception for invalid hex"
            except Exception:
                pass  # expected
            # test solver handles exception in solve method
            solver = solver_service._node
            test_info = SolverInfo(plot_strength=uint64(1000), partial_proof=b"test_partial_proof_zeros")
            with patch.object(solver, "solve", side_effect=RuntimeError("test error")):
                # solver api should handle exceptions gracefully
                result = await solver_service._api.solve(test_info)
                assert result is None  # api returns None on error
