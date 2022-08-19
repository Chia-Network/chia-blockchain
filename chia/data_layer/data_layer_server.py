import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import click
from aiohttp import web

from chia.cmds.chia import monkey_patch_click
from chia.data_layer.download_data import is_filename_valid
from chia.server.upnp import UPnP
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config
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

    async def start(self, ip: Optional[str], port: Optional[int]) -> None:
        self.log.info("Starting Data Layer Server.")
        if ip is not None:
            self.host_ip = ip
        else:
            self.host_ip = self.config["host_ip"]

        if port is None:
            self.port = self.config["host_port"]
        else:
            self.port = port

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
        self.site = web.TCPSite(self.runner, self.host_ip, port=self.port)
        await self.site.start()
        self.log.info("Started Data Layer Server.")
        shutdown_event = asyncio.Event()
        await shutdown_event.wait()

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


async def async_start(ip: Optional[str], port: Optional[int]) -> None:
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    setproctitle("data_layer_server")
    initialize_logging(
        service_name="data_layer_server",
        logging_config=config["logging"],
        root_path=DEFAULT_ROOT_PATH,
    )
    data_layer_server = DataLayerServer(DEFAULT_ROOT_PATH, config, log)
    await data_layer_server.start(ip, port)


@click.option("-i", "--ip", type=str, default=None)
@click.option("-p", "--port", type=int, default=None)
@click.command("start")
def start_cmd(ip: Optional[str], port: Optional[int]) -> None:
    asyncio.run(async_start(ip, port))


@click.group()
def cli() -> None:
    pass


cli.add_command(start_cmd)


def main() -> int:
    monkey_patch_click()
    cli()
    return 0


if __name__ == "__main__":
    sys.exit(main())
