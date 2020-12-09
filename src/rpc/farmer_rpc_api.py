from typing import Callable, Set, Dict, List

from src.farmer import Farmer
from src.util.ws_message import create_payload


class FarmerRpcApi:
    def __init__(self, farmer: Farmer):
        self.service = farmer
        self.service_name = "chia_farmer"

    def get_routes(self) -> Dict[str, Callable]:
        # return {"/get_latest_challenges": self.get_latest_challenges}
        return {}

    async def _state_changed(self, change: str) -> List[Dict]:
        # if change == "signage_point":
        #     data = await self.get_latest_challenges({})
        #     return [
        #         create_payload(
        #             "get_latest_challenges",
        #             data,
        #             self.service_name,
        #             "wallet_ui",
        #             string=False,
        #         )
        #     ]
        return []

    async def get_signage_point(self, request: Dict) -> Dict:
        response = []
        seen_challenges: Set = set()
        if self.service.current_weight == 0:
            return {"latest_challenges": []}
        for pospace_fin in self.service.challenges[self.service.current_weight]:
            estimates = self.service.challenge_to_estimates.get(pospace_fin.challenge, [])
            if pospace_fin.challenge in seen_challenges:
                continue
            response.append(
                {
                    "challenge": pospace_fin.challenge,
                    "weight": pospace_fin.weight,
                    "height": pospace_fin.height,
                    "difficulty": pospace_fin.difficulty,
                    "estimates": estimates,
                }
            )
            seen_challenges.add(pospace_fin.challenge)
        return {"latest_challenges": response}
