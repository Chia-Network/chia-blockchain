from typing import Dict, List, Optional

from src.rpc.rpc_client import RpcClient
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.byte_types import hexstr_to_bytes


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

    async def get_reward_targets(self, search_for_private_key: bool) -> Dict:
        response = await self.fetch("get_reward_targets", {"search_for_private_key": search_for_private_key})
        return_dict = {
            "farmer_target": hexstr_to_bytes(response["farmer_target"]),
            "pool_target": hexstr_to_bytes(response["pool_target"]),
        }
        if "have_pool_sk" in response:
            return_dict["have_pool_sk"] = response["have_pool_sk"]
        if "have_farmer_sk" in response:
            return_dict["have_farmer_sk"] = response["have_farmer_sk"]
        return return_dict

    async def set_reward_targets(
        self, farmer_target: Optional[bytes32] = None, pool_target: Optional[bytes32] = None
    ) -> Dict:
        request = {}
        if farmer_target is not None:
            request["farmer_target"] = farmer_target.hex()
        if pool_target is not None:
            request["pool_target"] = pool_target.hex()
        return await self.fetch("set_reward_targets", request)
