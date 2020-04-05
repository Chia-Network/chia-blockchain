import asyncio
import signal
import logging

try:
    import uvloop
except ImportError:
    uvloop = None

from src.farmer import Farmer
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo
from src.util.logging import initialize_logging
from src.util.config import load_config, load_config_cli
from src.util.setproctitle import setproctitle


async def main():
    config = load_config_cli("config.yaml", "farmer")
    try:
        key_config = load_config("keys.yaml")
    except FileNotFoundError:
        raise RuntimeError("Keys not generated. Run chia-generate-keys")
    initialize_logging("Farmer %(name)-25s", config["logging"])
    log = logging.getLogger(__name__)
    setproctitle("chia_farmer")

    farmer = Farmer(config, key_config)

    harvester_peer = PeerInfo(
        config["harvester_peer"]["host"], config["harvester_peer"]["port"]
    )
    full_node_peer = PeerInfo(
        config["full_node_peer"]["host"], config["full_node_peer"]["port"]
    )
    server = ChiaServer(config["port"], farmer, NodeType.FARMER)

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)

    _ = await server.start_server(farmer._on_connect, config)
    await asyncio.sleep(1)  # Prevents TCP simultaneous connect with harvester
    _ = await server.start_client(harvester_peer, None, config)
    _ = await server.start_client(full_node_peer, None, config)

    await server.await_closed()
    log.info("Farmer fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
