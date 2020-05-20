from typing import Callable, Set, Dict

from src.farmer import Farmer
from src.util.ints import uint16
from src.util.ws_message import create_payload
from src.rpc.abstract_rpc_server import AbstractRpcApiHandler, start_rpc_server


class FarmerRpcApiHandler(AbstractRpcApiHandler):
    def __init__(self, farmer: Farmer, stop_cb: Callable):
        super().__init__(farmer, stop_cb, "chia_farmer")

    async def _state_changed(self, change: str):
        assert self.websocket is not None

        if change == "challenge":
            data = await self.get_latest_challenges({})
            payload = create_payload(
                "get_latest_challenges", data, self.service_name, "wallet_ui"
            )
        else:
            await super()._state_changed(change)
            return
        try:
            await self.websocket.send_str(payload)
        except (BaseException) as e:
            try:
                self.log.warning(f"Sending data failed. Exception {type(e)}.")
            except BrokenPipeError:
                pass

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


async def start_farmer_rpc_server(
    farmer: Farmer, stop_node_cb: Callable, rpc_port: uint16
):
    handler = FarmerRpcApiHandler(farmer, stop_node_cb)
    routes = {"/get_latest_challenges": handler.get_latest_challenges}
    cleanup = await start_rpc_server(handler, rpc_port, routes)
    return cleanup


AbstractRpcApiHandler.register(FarmerRpcApiHandler)
