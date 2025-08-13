from __future__ import annotations

from typing import Any

from chia_rs.sized_bytes import bytes32

from chia.rpc.rpc_client import RpcClient


class SolverRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local solver. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    """

    async def get_state(self) -> dict[str, Any]:
        """Get solver state."""
        return await self.fetch("get_state", {})

    async def solve(self, quality_string: str, plot_size: int = 32, plot_difficulty: int = 1000) -> dict[str, Any]:
        """Solve a quality string with optional plot size and difficulty."""
        quality = bytes32.from_hexstr(quality_string)
        return await self.fetch(
            "solve", {"quality_string": quality.hex(), "plot_size": plot_size, "plot_difficulty": plot_difficulty}
        )
