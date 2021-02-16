from typing import Dict, List, Optional
from src.rpc.rpc_client import RpcClient
from src.types.blockchain_format.sized_bytes import bytes32


class FarmerRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local farmer. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP that provides easy access
    to the full node.
    """

    async def get_signage_point(self, sp_hash: bytes32) -> Optional[Dict]:
        try:
            return await self.fetch("get_signage_point", {"sp_hash": sp_hash.hex()})
        except ValueError:
            return None

    async def get_signage_points(self) -> List[Dict]:
        return (await self.fetch("get_signage_points", {}))["signage_points"]
