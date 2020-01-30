import asyncio
import signal
import logging

try:
    import uvloop
except ImportError:
    uvloop = None

from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.timelord import Timelord
from src.types.peer_info import PeerInfo
from src.util.logging import initialize_logging
from src.util.config import load_config_cli
from setproctitle import setproctitle

initialize_logging("Timelord %(name)-23s")
log = logging.getLogger(__name__)
setproctitle("chia_timelord")


async def main():
    config = load_config_cli("config.yaml", "timelord")
    timelord = Timelord(config)
    server = ChiaServer(config["port"], timelord, NodeType.TIMELORD)
    _ = await server.start_server(config["host"], None)

    def signal_received():
        server.close_all()
        asyncio.create_task(timelord._shutdown())

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, signal_received)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, signal_received)

    full_node_peer = PeerInfo(
        timelord.config["full_node_peer"]["host"],
        timelord.config["full_node_peer"]["port"],
    )

    await asyncio.sleep(1)  # Prevents TCP simultaneous connect with full node
    await server.start_client(full_node_peer, None)

    async for msg in timelord._manage_discriminant_queue():
        server.push_message(msg)

    await server.await_closed()
    log.info("Timelord fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
