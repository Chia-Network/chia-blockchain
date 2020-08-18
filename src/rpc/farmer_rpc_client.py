from typing import Dict, List
from src.rpc.rpc_client import RpcClient


class FarmerRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local farmer. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP thats provides easy access
    to the full node.
    """

    async def get_latest_challenges(self) -> List[Dict]:
        return await self.fetch("get_latest_challenges", {})
