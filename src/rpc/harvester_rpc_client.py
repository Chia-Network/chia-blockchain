from blspy import PrivateKey, PublicKey
from typing import Optional, List, Dict
from src.rpc.rpc_client import RpcClient


class HarvesterRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local harvester. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP thats provides easy access
    to the full node.
    """

    async def get_plots(self) -> List[Dict]:
        return await self.fetch("get_plots", {})

    async def refresh_plots(self) -> None:
        await self.fetch("refresh_plots", {})

    async def delete_plot(self, filename: str) -> bool:
        return await self.fetch("delete_plot", {"filename": filename})

    async def add_plot(
        self, filename: str, plot_sk: PrivateKey, pool_pk: Optional[PublicKey] = None
    ) -> bool:
        plot_sk_str = bytes(plot_sk).hex()
        if pool_pk is not None:
            pool_pk_str = bytes(pool_pk).hex()
            return await self.fetch(
                "add_plot",
                {"filename": filename, "plot_sk": plot_sk_str, "pool_pk": pool_pk_str},
            )
        else:
            return await self.fetch(
                "add_plot", {"filename": filename, "plot_sk": plot_sk_str}
            )
