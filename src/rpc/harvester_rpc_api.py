from typing import Callable, Dict, List

from src.harvester import Harvester
from src.util.ws_message import create_payload


class HarvesterRpcApi:
    def __init__(self, harvester: Harvester):
        self.service = harvester
        self.service_name = "chia_harvester"

    def get_routes(self) -> Dict[str, Callable]:
        return {
            "/get_plots": self.get_plots,
            "/refresh_plots": self.refresh_plots,
            "/delete_plot": self.delete_plot,
            "/add_plot_directory": self.add_plot_directory,
            "/get_plot_directories": self.get_plot_directories,
            "/remove_plot_directory": self.remove_plot_directory,
        }

    async def _state_changed(self, change: str) -> List[Dict]:
        if change == "plots":
            data = await self.get_plots({})
            payload = create_payload(
                "get_plots", data, self.service_name, "wallet_ui", string=False
            )
            return [payload]
        return []

    async def get_plots(self, request: Dict) -> Dict:
        plots, failed_to_open, not_found = self.service._get_plots()
        return {
            "plots": plots,
            "failed_to_open_filenames": failed_to_open,
            "not_found_filenames": not_found,
        }

    async def refresh_plots(self, request: Dict) -> Dict:
        await self.service._refresh_plots()
        return {}

    async def delete_plot(self, request: Dict) -> Dict:
        filename = request["filename"]
        if self.service._delete_plot(filename):
            return {}
        raise ValueError(f"Not able to delete file {filename}")

    async def add_plot_directory(self, request: Dict) -> Dict:
        dirname = request["dirname"]
        if await self.service._add_plot_directory(dirname):
            return {}
        raise ValueError(f"Did not add plot directory {dirname}")

    async def get_plot_directories(self, request: Dict) -> Dict:
        plot_dirs = await self.service._get_plot_directories()
        return {"directories": plot_dirs}

    async def remove_plot_directory(self, request: Dict) -> Dict:
        dirname = request["dirname"]
        if await self.service._remove_plot_directory(dirname):
            return {}
        raise ValueError(f"Did not remove plot directory {dirname}")
