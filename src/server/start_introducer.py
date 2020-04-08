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
from src.util.config import load_config_cli, load_config
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.logging import initialize_logging
from src.util.setproctitle import setproctitle


async def main():
    root_path = DEFAULT_ROOT_PATH
    net_config = load_config(root_path, "config.yaml")
    config = load_config_cli(root_path, "config.yaml", "introducer")
    initialize_logging("Introducer %(name)-21s", config["logging"])
    log = logging.getLogger(__name__)
    setproctitle("chia_introducer")

    introducer = Introducer(config)
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")
    server = ChiaServer(config["port"], introducer, NodeType.INTRODUCER, ping_interval, network_id)
    introducer.set_server(server)
    _ = await server.start_server(None, config)

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)

    await server.await_closed()
    log.info("Introducer fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
