from typing import Callable, Dict
from blspy import PrivateKey, PublicKey

from src.harvester import Harvester
from src.util.ints import uint16
from src.util.ws_message import create_payload
from src.rpc.abstract_rpc_server import AbstractRpcApiHandler, start_rpc_server


class HarvesterRpcApiHandler(AbstractRpcApiHandler):
    def __init__(self, harvester: Harvester, stop_cb: Callable):
        super().__init__(harvester, stop_cb, "chia_harvester")

    async def _state_changed(self, change: str):
        assert self.websocket is not None

        if change == "plots":
            data = await self.get_plots({})
            payload = create_payload("get_plots", data, self.service_name, "wallet_ui")
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


async def start_harvester_rpc_server(
    harvester: Harvester, stop_node_cb: Callable, rpc_port: uint16
):
    handler = HarvesterRpcApiHandler(harvester, stop_node_cb)
    routes = {
        "/get_plots": handler.get_plots,
        "/refresh_plots": handler.refresh_plots,
        "/delete_plot": handler.delete_plot,
        "/add_plot": handler.add_plot,
    }
    cleanup = await start_rpc_server(handler, rpc_port, routes)
    return cleanup


AbstractRpcApiHandler.register(HarvesterRpcApiHandler)
