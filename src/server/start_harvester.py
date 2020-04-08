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
from src.util.config import load_config, load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.logging import initialize_logging
from src.util.setproctitle import setproctitle


async def main():
    root_path = DEFAULT_ROOT_PATH
    net_config = load_config(root_path, "config.yaml")
    config = load_config_cli(root_path, "config.yaml", "harvester")
    try:
        plot_config = load_config(root_path, "plots.yaml")
    except FileNotFoundError:
        raise RuntimeError("Plots not generated. Run chia-create-plots")

    initialize_logging("Harvester %(name)-22s", config["logging"])
    log = logging.getLogger(__name__)
    setproctitle("chia_harvester")

    harvester = Harvester(config, plot_config)
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")
    server = ChiaServer(config["port"], harvester, NodeType.HARVESTER, ping_interval, network_id)
    _ = await server.start_server(None, config)

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)

    peer_info = PeerInfo(
        harvester.config["farmer_peer"]["host"], harvester.config["farmer_peer"]["port"]
    )

    _ = await server.start_client(peer_info, None, config)
    await server.await_closed()
    harvester._shutdown()
    await harvester._await_shutdown()
    log.info("Harvester fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
