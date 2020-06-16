from typing import Callable, Set, Dict, List

from src.farmer import Farmer
from src.util.ws_message import create_payload


class FarmerRpcApi:
    def __init__(self, farmer: Farmer):
        self.service = farmer
        self.service_name = "chia_farmer"

    def get_routes(self) -> Dict[str, Callable]:
        return {"/get_latest_challenges": self.get_latest_challenges}

    async def _state_changed(self, change: str) -> List[str]:
        if change == "challenge":
            data = await self.get_latest_challenges({})
            return [
                create_payload(
                    "get_latest_challenges", data, self.service_name, "wallet_ui"
                )
            ]
        return []

    async def get_latest_challenges(self, request: Dict) -> Dict:
        response = []
        seen_challenges: Set = set()
        if self.service.current_weight == 0:
            return {"success": True, "latest_challenges": []}
        for pospace_fin in self.service.challenges[self.service.current_weight]:
            estimates = self.service.challenge_to_estimates.get(
                pospace_fin.challenge_hash, []
            )
            if pospace_fin.challenge_hash in seen_challenges:
                continue
            response.append(
                {
                    "challenge": pospace_fin.challenge_hash,
                    "weight": pospace_fin.weight,
                    "height": pospace_fin.height,
                    "difficulty": pospace_fin.difficulty,
                    "estimates": estimates,
                }
            )
            seen_challenges.add(pospace_fin.challenge_hash)
        return {"success": True, "latest_challenges": response}
