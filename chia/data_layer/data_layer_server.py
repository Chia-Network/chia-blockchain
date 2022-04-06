import os
import logging
from typing import Any, Dict
from pathlib import Path
from aiohttp import web
from dataclasses import dataclass
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
        self.upnp: UPnP = UPnP()  # type: ignore[no-untyped-call]
        self.upnp.remap(self.port)  # type: ignore[no-untyped-call]

        server_files_replaced: str = self.config["server_files_location"].replace(
            "CHALLENGE", self.config["selected_network"]
        )
        self.server_dir = path_from_root(self.root_path, server_files_replaced)

        app = web.Application()
        app.add_routes([web.get("/{filename}", self.file_handler)])
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.config["host_ip"], port=self.port)
        await self.site.start()
        self.log.info("Started Data Layer Server.")

    async def stop(self) -> None:
        self.upnp.release(self.port)  # type: ignore[no-untyped-call]
        # this is a blocking call, waiting for the UPnP thread to exit
        self.upnp.shutdown()  # type: ignore[no-untyped-call]

        self.log.info("Stopped Data Layer Server.")
        await self.runner.cleanup()

    async def file_handler(self, request: web.Request) -> web.Response:
        filename = request.match_info["filename"]
        file_path = os.path.join(self.server_dir, filename)
        if os.path.exists(file_path):
            with open(file_path, "rb") as reader:
                content = reader.read()
            if content:
                response = web.Response(
                    content_type="application/octet-stream",
                    headers={"Content-Disposition": "attachment;filename={}".format(filename)},
                    body=content,
                )
                return response

        raise RuntimeError("Couldn't find the file.")
