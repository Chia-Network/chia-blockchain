import asyncio
import logging
import signal

import uvloop

from src.harvester import Harvester
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo
from src.util.network import parse_host_port
from setproctitle import setproctitle

logging.basicConfig(
    format="Harvester %(name)-24s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)
setproctitle("chia_harvester")


async def main():
    harvester = Harvester()
    host, port = parse_host_port(harvester)
    server = ChiaServer(port, harvester, NodeType.HARVESTER)
    _ = await server.start_server(host, None)

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)

    peer_info = PeerInfo(
        harvester.config["farmer_peer"]["host"], harvester.config["farmer_peer"]["port"]
    )

    _ = await server.start_client(peer_info, None)
    await server.await_closed()
    harvester._shutdown()
    await harvester._await_shutdown()


uvloop.install()
asyncio.run(main())
