from typing import Callable, Dict, List

from chia.harvester.harvester import Harvester
from chia.util.ws_message import WsRpcMessage, create_payload_dict


class HarvesterRpcApi:
    def __init__(self, harvester: Harvester):
        self.service = harvester
        self.service_name = "sit_harvester"

    def get_routes(self) -> Dict[str, Callable]:
        return {
            "/get_plots": self.get_plots,
            "/refresh_plots": self.refresh_plots,
            "/delete_plot": self.delete_plot,
            "/add_plot_directory": self.add_plot_directory,
            "/get_plot_directories": self.get_plot_directories,
            "/remove_plot_directory": self.remove_plot_directory,
        }

    async def _state_changed(self, change: str) -> List[WsRpcMessage]:
        if change == "plots":
            data = await self.get_plots({})
            payload = create_payload_dict("get_plots", data, self.service_name, "wallet_ui")
            return [payload]
        return []

    async def get_plots(self, request: Dict) -> Dict:
        plots, failed_to_open, not_found = self.service.get_plots()
        return {
            "plots": plots,
            "failed_to_open_filenames": failed_to_open,
            "not_found_filenames": not_found,
        }

    async def refresh_plots(self, request: Dict) -> Dict:
        self.service.plot_manager.trigger_refresh()
        return {}

    async def delete_plot(self, request: Dict) -> Dict:
        filename = request["filename"]
        if self.service.delete_plot(filename):
            return {}
        raise ValueError(f"Not able to delete file {filename}")

    async def add_plot_directory(self, request: Dict) -> Dict:
        directory_name = request["dirname"]
        if await self.service.add_plot_directory(directory_name):
            return {}
        raise ValueError(f"Did not add plot directory {directory_name}")

    async def get_plot_directories(self, request: Dict) -> Dict:
        plot_dirs = await self.service.get_plot_directories()
        return {"directories": plot_dirs}

    async def remove_plot_directory(self, request: Dict) -> Dict:
        directory_name = request["dirname"]
        if await self.service.remove_plot_directory(directory_name):
            return {}
        raise ValueError(f"Did not remove plot directory {directory_name}")
