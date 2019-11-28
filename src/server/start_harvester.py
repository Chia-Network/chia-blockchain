import asyncio
import logging
import signal
import uvloop

from src.harvester import Harvester
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo
from src.util.network import parse_host_port

logging.basicConfig(
    format="Harvester %(name)-24s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)


async def main():
    harvester = Harvester()
    host, port = parse_host_port(harvester)
    server = ChiaServer(port, harvester, NodeType.HARVESTER)
    _ = await server.start_server(host, None)

    def signal_received():
        server.close_all()

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, signal_received)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, signal_received)

    peer_info = PeerInfo(
        harvester.config["farmer_peer"]["host"], harvester.config["farmer_peer"]["port"]
    )

    _ = await server.start_client(peer_info, None)
    await server.await_closed()


uvloop.install()
asyncio.run(main())
