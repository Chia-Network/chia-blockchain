import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from aiohttp import web

from chia.data_layer.download_data import is_filename_valid
from chia.server.start_service import async_run
from chia.server.upnp import UPnP
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config, load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.path import path_from_root
from chia.util.setproctitle import setproctitle

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "data_layer"
log = logging.getLogger(__name__)


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
        while True:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self.upnp.release(self.port)
        # this is a blocking call, waiting for the UPnP thread to exit
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


async def async_main() -> int:
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    service_config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    config[SERVICE_NAME] = service_config
    setproctitle("data_layer_server")
    initialize_logging(
        service_name="data_layer_server",
        logging_config=service_config["logging"],
        root_path=DEFAULT_ROOT_PATH,
    )
    data_layer_server = DataLayerServer(DEFAULT_ROOT_PATH, config[SERVICE_NAME], log)
    await data_layer_server.start()
    return 0


def main() -> int:
    async_run(async_main())
    return 0


if __name__ == "__main__":
    sys.exit(main())
