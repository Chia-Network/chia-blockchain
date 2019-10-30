import asyncio
import logging
from src.server.server import ChiaServer
from src.server.outbound_message import NodeType
from src.util.network import parse_host_port
from src.plotter import Plotter

logging.basicConfig(format='Plotter %(name)-24s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s',
                    level=logging.INFO,
                    datefmt='%H:%M:%S'
                    )


async def main():
    plotter = Plotter()
    host, port = parse_host_port(plotter)
    server = ChiaServer(port, plotter, NodeType.PLOTTER)
    _ = await server.start_server(host, NodeType.FARMER, None)
    await server.await_closed()

asyncio.run(main())
