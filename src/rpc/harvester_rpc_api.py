from typing import Callable, Dict, List

from src.harvester import Harvester
from src.util.ws_message import create_payload
from blspy import PrivateKey, PublicKey


class HarvesterRpcApi:
    def __init__(self, harvester: Harvester):
        self.service = harvester
        self.service_name = "chia_harvester"

    def get_routes(self) -> Dict[str, Callable]:
        return {
            "/get_plots": self.get_plots,
            "/refresh_plots": self.refresh_plots,
            "/delete_plot": self.delete_plot,
            "/add_plot": self.add_plot,
        }

    async def _state_changed(self, change: str) -> List[str]:
        if change == "plots":
            data = await self.get_plots({})
            payload = create_payload("get_plots", data, self.service_name, "wallet_ui")
            return [payload]
        return []

    async def get_plots(self, request: Dict) -> Dict:
        plots, failed_to_open, not_found = self.service._get_plots()
        return {
            "success": True,
            "plots": plots,
            "failed_to_open_filenames": failed_to_open,
            "not_found_filenames": not_found,
        }

    async def refresh_plots(self, request: Dict) -> Dict:
        self.service._refresh_plots()
        return {"success": True}

    async def delete_plot(self, request: Dict) -> Dict:
        filename = request["filename"]
        success = self.service._delete_plot(filename)
        return {"success": success}

    async def add_plot(self, request: Dict) -> Dict:
        filename = request["filename"]
        if "pool_pk" in request:
            pool_pk = PublicKey.from_bytes(bytes.fromhex(request["pool_pk"]))
        else:
            pool_pk = None
        plot_sk = PrivateKey.from_bytes(bytes.fromhex(request["plot_sk"]))
        success = self.service._add_plot(filename, plot_sk, pool_pk)
        return {"success": success}
