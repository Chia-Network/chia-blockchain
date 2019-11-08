import asyncio
import logging
import signal
import sys
from src.types.peer_info import PeerInfo
from src.server.server import ChiaServer
from src.server.outbound_message import NodeType
from src.util.network import parse_host_port
from src.timelord import Timelord

logging.basicConfig(format='Timelord %(name)-25s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s',
                    level=logging.INFO,
                    datefmt='%H:%M:%S'
                    )


async def main():
    timelord = Timelord()
    host, port = parse_host_port(timelord)
    server = ChiaServer(port, timelord, NodeType.TIMELORD)
    _ = await server.start_server(host, None)

    def signal_received():
        server.close_all()
        sys.exit()
    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, signal_received)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, signal_received)

    full_node_peer = PeerInfo(timelord.config['full_node_peer']['host'],
                              timelord.config['full_node_peer']['port'])

    await server.start_client(full_node_peer, None)

    await server.await_closed()

asyncio.run(main())
