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
from src.util.config import load_config, load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.logging import initialize_logging
from src.util.setproctitle import setproctitle


async def main():
    root_path = DEFAULT_ROOT_PATH
    net_config = load_config(root_path, "config.yaml")
    config = load_config_cli(root_path, "config.yaml", "farmer")
    try:
        key_config = load_config(root_path, "keys.yaml")
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
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")
    assert ping_interval is not None
    assert network_id is not None
    server = ChiaServer(
        config["port"], farmer, NodeType.FARMER, ping_interval, network_id
    )

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)

    _ = await server.start_server(farmer._on_connect, config)
    await asyncio.sleep(1)  # Prevents TCP simultaneous connect with harvester
    _ = await server.start_client(harvester_peer, None, config)
    _ = await server.start_client(full_node_peer, None, config)

    farmer.set_server(server)
    farmer._start_bg_tasks()

    await server.await_closed()
    farmer._shut_down = True
    log.info("Farmer fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
