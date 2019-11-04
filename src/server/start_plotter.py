import asyncio
import logging
from src.server.server import ChiaServer
from src.server.outbound_message import NodeType
from src.util.network import parse_host_port
from src.types.peer_info import PeerInfo
from src.plotter import Plotter

logging.basicConfig(format='Plotter %(name)-24s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s',
                    level=logging.INFO,
                    datefmt='%H:%M:%S'
                    )


async def main():
    plotter = Plotter()
    host, port = parse_host_port(plotter)
    server = ChiaServer(port, plotter, NodeType.PLOTTER)
    _ = await server.start_server(host, None)

    peer_info = PeerInfo(plotter.config['farmer_peer']['host'],
                         plotter.config['farmer_peer']['port'],
                         bytes.fromhex(plotter.config['farmer_peer']['node_id']))

    _ = await server.start_client(peer_info, None)

    await server.await_closed()

asyncio.run(main())
