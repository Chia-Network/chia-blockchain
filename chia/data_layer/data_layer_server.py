import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from aiohttp import web

from chia.data_layer.download_data import is_filename_valid
from chia.server.upnp import UPnP
from chia.util.path import path_from_root


@dataclass
class DataLayerServer:
    root_path: Path
    config: Dict[str, Any]
    log: logging.Logger

    async def start(self) -> None:
        self.log.info("Starting Data Layer Server.")
        self.port = self.config["host_port"]

        # Setup UPnP for the data_layer_service port
        self.upnp: UPnP = UPnP()
        self.upnp.remap(self.port)

        server_files_replaced: str = self.config.get(
            "server_files_location", "data_layer/db/server_files_location_CHALLENGE"
        ).replace("CHALLENGE", self.config["selected_network"])
        self.server_dir = path_from_root(self.root_path, server_files_replaced)

        app = web.Application()
        app.add_routes([web.get("/{filename}", self.file_handler)])
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.config["host_ip"], port=self.port)
        await self.site.start()
        self.log.info("Started Data Layer Server.")

    async def stop(self) -> None:
        self.upnp.release(self.port)
        # UPnP.shutdown() is a blocking call, waiting for the UPnP thread to exit
        self.upnp.shutdown()

        self.log.info("Stopped Data Layer Server.")
        await self.runner.cleanup()

    async def file_handler(self, request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        if not is_filename_valid(filename):
            raise Exception("Invalid file format requested.")
        file_path = self.server_dir.joinpath(filename)
        with open(file_path, "rb") as reader:
            content = reader.read()
        response = web.Response(
            content_type="application/octet-stream",
            headers={"Content-Disposition": "attachment;filename={}".format(filename)},
            body=content,
        )
        return response
