from __future__ import annotations

from typing import Any, Dict, List

from chia.harvester.harvester import Harvester
from chia.rpc.rpc_server import Endpoint, EndpointResult
from chia.util.ws_message import WsRpcMessage, create_payload_dict


class HarvesterRpcApi:
    def __init__(self, harvester: Harvester):
        self.service = harvester
        self.service_name = "chia_harvester"

    def get_routes(self) -> Dict[str, Endpoint]:
        return {
            "/get_plots": self.get_plots,
            "/refresh_plots": self.refresh_plots,
            "/delete_plot": self.delete_plot,
            "/add_plot_directory": self.add_plot_directory,
            "/get_plot_directories": self.get_plot_directories,
            "/remove_plot_directory": self.remove_plot_directory,
        }

    async def _state_changed(self, change: str, change_data: Dict[str, Any] = None) -> List[WsRpcMessage]:
        if change_data is None:
            change_data = {}

        payloads = []

        if change == "plots":
            data = await self.get_plots({})
            payload = create_payload_dict("get_plots", data, self.service_name, "wallet_ui")
            payloads.append(payload)

        if change == "farming_info":
            payloads.append(create_payload_dict("farming_info", change_data, self.service_name, "metrics"))

        if change == "add_connection":
            payloads.append(create_payload_dict("add_connection", change_data, self.service_name, "metrics"))

        if change == "close_connection":
            payloads.append(create_payload_dict("close_connection", change_data, self.service_name, "metrics"))

        return payloads

    async def get_plots(self, request: Dict) -> EndpointResult:
        plots, failed_to_open, not_found = self.service.get_plots()
        return {
            "plots": plots,
            "failed_to_open_filenames": failed_to_open,
            "not_found_filenames": not_found,
        }

    async def refresh_plots(self, request: Dict) -> EndpointResult:
        self.service.plot_manager.trigger_refresh()
        return {}

    async def delete_plot(self, request: Dict) -> EndpointResult:
        filename = request["filename"]
        if self.service.delete_plot(filename):
            return {}
        raise ValueError(f"Not able to delete file {filename}")

    async def add_plot_directory(self, request: Dict) -> EndpointResult:
        directory_name = request["dirname"]
        if await self.service.add_plot_directory(directory_name):
            return {}
        raise ValueError(f"Did not add plot directory {directory_name}")

    async def get_plot_directories(self, request: Dict) -> EndpointResult:
        plot_dirs = await self.service.get_plot_directories()
        return {"directories": plot_dirs}

    async def remove_plot_directory(self, request: Dict) -> EndpointResult:
        directory_name = request["dirname"]
        if await self.service.remove_plot_directory(directory_name):
            return {}
        raise ValueError(f"Did not remove plot directory {directory_name}")
