from typing import Callable, Dict, List

from src.farmer.farmer import Farmer
from src.types.sized_bytes import bytes32
from src.util.ws_message import create_payload


class FarmerRpcApi:
    def __init__(self, farmer: Farmer):
        self.service = farmer
        self.service_name = "chia_farmer"

    def get_routes(self) -> Dict[str, Callable]:
        return {
            "/get_signage_point": self.get_signage_point,
            "/get_signage_points": self.get_signage_points,
        }

    async def _state_changed(self, change: str, sp_hash: bytes32) -> List[Dict]:
        if change == "signage_point":
            data = await self.get_signage_point({"sp_hash": sp_hash})
            return [
                create_payload(
                    "get_signage_point",
                    data,
                    self.service_name,
                    "wallet_ui",
                    string=False,
                )
            ]
        return []

    async def get_signage_point(self, request: Dict) -> Dict:
        for _, sps in self.service.sps:
            for sp in sps:
                if sp.challenge_chain_sp == request["sp_hash"]:
                    pospaces = self.service.proofs_of_space[sp.challenge_chain_sp]
                    return {"signage_point": sp, "proofs": pospaces}
        raise ValueError(f"Signage point {request['sp_hash'].hex()} not found")

    async def get_signage_points(self, _: Dict) -> Dict:
        result: Dict = {}
        for _, sps in self.service.sps:
            for sp in sps:
                pospaces = self.service.proofs_of_space[sp.challenge_chain_sp]
                result[sp.challenge_chain_sp] = {"sp_hash": sp, "proofs": pospaces}
        return result
