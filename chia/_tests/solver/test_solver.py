from __future__ import annotations

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia.protocols.solver_protocol import SolverInfo
from chia.server.aliases import SolverService


@pytest.mark.anyio
async def test_solver_solve(solver_service: SolverService) -> None:
    """Test that the solver service can process a solve request."""
    solver = solver_service._node
    solver_api = solver_service._api

    # Create test SolverInfo
    test_info = SolverInfo(plot_size=uint8(32), plot_diffculty=uint64(1000), quality_string=bytes32.zeros)

    # Call solve directly on the solver
    result = solver.solve(test_info)

    # Should return None since it's not implemented
    assert result is None

    # Test through the API
    api_result = await solver_api.solve(test_info)

    # Should return None since solver.solve returns None
    assert api_result is None
