import asyncio
import functools
import logging
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import click
from aiohttp import web

from chia.data_layer.download_data import is_filename_valid
from chia.server.upnp import UPnP
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.path import path_from_root
from chia.util.setproctitle import setproctitle

# from chia.cmds.chia import monkey_patch_click


# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "data_layer"
log = logging.getLogger(__name__)


@dataclass
class DataLayerServer:
    root_path: Path
    config: Dict[str, Any]
    log: logging.Logger
    stopped_event: asyncio.Event = field(default_factory=asyncio.Event)
    _stop_task: Optional[asyncio.Task[None]] = None

    async def run(self) -> None:
        await self.start()
        await self.stopped_event.wait()

    async def start(self) -> None:

        if sys.platform == "win32" or sys.platform == "cygwin":
            # pylint: disable=E1101
            signal.signal(signal.SIGBREAK, self._accept_signal)
            signal.signal(signal.SIGINT, self._accept_signal)
            signal.signal(signal.SIGTERM, self._accept_signal)
        else:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(
                signal.SIGINT,
                functools.partial(self._accept_signal, signal_number=signal.SIGINT),
            )
            loop.add_signal_handler(
                signal.SIGTERM,
                functools.partial(self._accept_signal, signal_number=signal.SIGTERM),
            )

        self.log.info("Starting Data Layer HTTP Server.")

        self.host_ip = self.config["host_ip"]
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
        self.site = web.TCPSite(self.runner, self.host_ip, port=self.port)
        await self.site.start()
        self.log.info("Started Data Layer HTTP Server.")

    def stop(self) -> None:
        self.upnp.release(self.port)
        # UPnP.shutdown() is a blocking call, waiting for the UPnP thread to exit
        self.upnp.shutdown()

        self._stop_task = asyncio.create_task(self._async_stop())

        self.log.info("Stopping Data Layer HTTP Server.")

    async def _async_stop(self) -> None:
        await self.runner.cleanup()
        self.log.info("Data Layer HTTP Server stopped.")
        self.stopped_event.set()

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

    def _accept_signal(self, signal_number: int, stack_frame: Any = None) -> None:
        self.log.info(f"Stopping due to receiving signal: {signal_number}")

        self.stop()


async def async_start(root_path: Path) -> int:
    dl_config = load_config(root_path=root_path, filename="config.yaml", sub_config=SERVICE_NAME)
    setproctitle("chia_data_layer_http")
    initialize_logging(
        service_name="data_layer_http",
        logging_config=dl_config["logging"],
        root_path=root_path,
    )

    data_layer_server = DataLayerServer(root_path, dl_config, log)
    await data_layer_server.run()

    return 0


@click.command()
@click.option(
    "-r",
    "--root-path",
    type=click.Path(exists=True, writable=True, file_okay=False),
    default=DEFAULT_ROOT_PATH,
    show_default=True,
    help="Config file root",
)
def main(root_path: str) -> int:
    return asyncio.run(async_start(Path(root_path)))


if __name__ == "__main__":
    sys.exit(main())  # pylint: disable=E1120
