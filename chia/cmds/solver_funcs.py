from __future__ import annotations

import json
from typing import Optional

from chia.cmds.cmd_classes import ChiaCliContext
from chia.cmds.cmds_util import get_any_service_client
from chia.solver.solver_rpc_client import SolverRpcClient


async def get_state(
    ctx: ChiaCliContext,
    solver_rpc_port: Optional[int] = None,
) -> None:
    """Get solver state via RPC."""
    try:
        async with get_any_service_client(SolverRpcClient, ctx.root_path, solver_rpc_port) as (client, _):
            response = await client.get_state()
            print(json.dumps(response, indent=2))
    except Exception as e:
        print(f"Failed to get solver state: {e}")
