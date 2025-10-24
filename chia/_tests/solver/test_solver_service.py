from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from chia_rs import ConsensusConstants
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia.protocols.outbound_message import Message
from chia.protocols.solver_protocol import SolverInfo
from chia.simulator.block_tools import create_block_tools_async
from chia.simulator.keyring import TempKeyring
from chia.simulator.setup_services import setup_solver


@pytest.mark.anyio
async def test_solver_api_methods(blockchain_constants: ConsensusConstants, tmp_path: Path) -> None:
    with TempKeyring(populate=True) as keychain:
        bt = await create_block_tools_async(constants=blockchain_constants, keychain=keychain)
        async with setup_solver(tmp_path, bt, blockchain_constants) as solver_service:
            solver = solver_service._node
            solver_api = solver_service._api
            assert solver_api.ready() is True
            test_info = SolverInfo(
                partial_proof=[uint64(1000), uint64(2000), uint64(3000), uint64(4000)],
                plot_id=bytes32.fromhex("abababababababababababababababababababababababababababababababab"),
                strength=uint8(5),
                size=uint8(28),
            )
            expected_proof = b"test_proof_data_12345"
            with patch.object(solver, "solve", return_value=expected_proof):
                api_result = await solver_api.solve(test_info)
                assert api_result is not None
                assert isinstance(api_result, Message)
