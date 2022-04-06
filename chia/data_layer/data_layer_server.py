import os
import logging
from typing import Any, Dict, Optional
from aiohttp import web
from dataclasses import dataclass
from chia.server.upnp import UPnP


@dataclass
class DataLayerServer:
    config: Dict[str, Any]
    log: logging.Logger

    async def start(self) -> None:
        self.log.info("Starting Data Layer Server.")
        self.port = self.config["host_port"]

        # Setup UPnP for the data_layer_service port
        self.upnp: UPnP = UPnP()  # type: ignore[no-untyped-call]
        self.upnp.remap(self.port)  # type: ignore[no-untyped-call]

        app = web.Application()
        app.router.add_route("GET", "/", self.file_handler)
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

    async def file_handler(self, filename: str) -> Optional[web.Response]:
        file_dir = self.config.get("server_files_location", "data_layer/db/server_files_location")
        file_path = os.path.join(file_dir, filename)
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
            else:
                return None
        else:
            return None
