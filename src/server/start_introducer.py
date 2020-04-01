import asyncio
import signal
import logging

try:
    import uvloop
except ImportError:
    uvloop = None

from src.introducer import Introducer
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.util.logging import initialize_logging
from src.util.config import load_config_cli
from src.util.setproctitle import setproctitle


async def main():
    config = load_config_cli("config.yaml", "introducer")

    initialize_logging("Introducer %(name)-21s", config["logging"])
    log = logging.getLogger(__name__)
    setproctitle("chia_introducer")

    introducer = Introducer(config)
    server = ChiaServer(config["port"], introducer, NodeType.INTRODUCER)
    introducer.set_server(server)
    _ = await server.start_server(config["host"], None, config)

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)

    await server.await_closed()
    log.info("Introducer fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
