from typing import Any
from aiohttp import web
import asyncio
from pathlib import Path
import logging


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
