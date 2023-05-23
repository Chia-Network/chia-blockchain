from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)


class AlertServer:
    shut_down: bool
    shut_down_event: asyncio.Event
    log: Any
    app: Any
    alert_file_path: Path
    port: int

    @staticmethod
    async def create_alert_server(alert_file_path: Path, port):
        self = AlertServer()
        self.log = log
        self.shut_down = False
        self.app = web.Application()
        self.shut_down_event = asyncio.Event()
        self.port = port
        routes = [
            web.get("/status", self.status),
        ]

        self.alert_file_path = alert_file_path
        self.app.add_routes(routes)

        return self

    async def status(self, request):
        file_text = self.alert_file_path.read_text()
        return web.Response(body=file_text, content_type="text/plain")

    async def stop(self):
        self.shut_down_event.set()

    async def run(self):
        runner = web.AppRunner(self.app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, None, self.port)
        await site.start()


async def run_and_wait(file_path, port):
    server = await AlertServer.create_alert_server(Path(file_path), port)
    await server.run()
    await server.shut_down_event.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-file_path", type=str, dest="file_path")
    parser.add_argument("-port", type=str, dest="port")

    port = None
    file_path = None

    for key, value in vars(parser.parse_args()).items():
        if key == "port":
            port = value
        elif key == "file_path":
            file_path = value
        else:
            print(f"Invalid argument {key}")

    if port is None or file_path is None:
        print(
            "Missing arguments, example usage:\n\n"
            "python chia/util/alert_server.py -p 4000 -file_path /home/user/alert.txt\n"
        )
        quit()

    return asyncio.run(run_and_wait(file_path, port))


if __name__ == "__main__":
    main()
