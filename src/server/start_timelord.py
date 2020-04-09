import asyncio
import signal
import logging
from typing import Optional

from src.consensus.constants import constants

try:
    import uvloop
except ImportError:
    uvloop = None

from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.timelord import Timelord
from src.types.peer_info import PeerInfo
from src.util.config import load_config_cli, load_config
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.logging import initialize_logging
from src.util.setproctitle import setproctitle


async def async_main():
    root_path = DEFAULT_ROOT_PATH
    net_config = load_config(root_path, "config.yaml")
    config = load_config_cli(root_path, "config.yaml", "timelord")
    initialize_logging("Timelord %(name)-23s", config["logging"])
    log = logging.getLogger(__name__)
    setproctitle("chia_timelord")

    timelord = Timelord(config, constants)
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")
    assert ping_interval is not None
    assert network_id is not None
    server = ChiaServer(
        config["port"], timelord, NodeType.TIMELORD, ping_interval, network_id
    )
    _ = await server.start_server(None, config)

    timelord_shutdown_task: Optional[asyncio.Task] = None

    coro = asyncio.start_server(
        timelord._handle_client,
        config["vdf_server"]["host"],
        config["vdf_server"]["port"],
        loop=asyncio.get_running_loop(),
    )

    def signal_received():
        nonlocal timelord_shutdown_task
        server.close_all()
        timelord_shutdown_task = asyncio.create_task(timelord._shutdown())

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, signal_received)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, signal_received)

    full_node_peer = PeerInfo(
        timelord.config["full_node_peer"]["host"],
        timelord.config["full_node_peer"]["port"],
    )

    await asyncio.sleep(1)  # Prevents TCP simultaneous connect with full node
    await server.start_client(full_node_peer, None, config)

    vdf_server = asyncio.ensure_future(coro)

    async for msg in timelord._manage_discriminant_queue():
        server.push_message(msg)

    log.info("Closed discriminant queue.")
    if timelord_shutdown_task is not None:
        await timelord_shutdown_task
    log.info("Shutdown timelord.")

    await server.await_closed()
    vdf_server.cancel()
    log.info("Timelord fully closed.")


def main():
    if uvloop is not None:
        uvloop.install()
    asyncio.run(async_main())


if __name__ == '__main__':
    main()
