from __future__ import annotations

from typing import Any

from chia.rpc.rpc_client import RpcClient


class SolverRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local solver. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    """

    async def get_state(self) -> dict[str, Any]:
        """Get solver state."""
        return await self.fetch("get_state", {})

    async def solve(self, partial_proof: str) -> dict[str, Any]:
        """Solve a partial proof."""
        return await self.fetch("solve", {"partial_proof": partial_proof})
