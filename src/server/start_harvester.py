import asyncio
import signal
import logging

try:
    import uvloop
except ImportError:
    uvloop = None

from src.harvester import Harvester
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo
from src.util.logging import initialize_logging
from src.util.config import load_config, load_config_cli
from setproctitle import setproctitle

initialize_logging("Harvester %(name)-22s")
log = logging.getLogger(__name__)
setproctitle("chia_harvester")


async def main():
    config = load_config_cli("config.yaml", "harvester")
    try:
        key_config = load_config("keys.yaml")
    except FileNotFoundError:
        raise RuntimeError(
            "Keys not generated. Run python3 ./scripts/regenerate_keys.py."
        )
    try:
        plot_config = load_config("plots.yaml")
    except FileNotFoundError:
        raise RuntimeError(
            "Plots not generated. Run python3.7 ./scripts/create_plots.py."
        )
    harvester = Harvester(config, key_config, plot_config)
    server = ChiaServer(config["port"], harvester, NodeType.HARVESTER)
    _ = await server.start_server(config["port"], None)

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)

    peer_info = PeerInfo(
        harvester.config["farmer_peer"]["host"], harvester.config["farmer_peer"]["port"]
    )

    _ = await server.start_client(peer_info, None)
    await server.await_closed()
    harvester._shutdown()
    await harvester._await_shutdown()
    log.info("Harvester fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
