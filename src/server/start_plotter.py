import asyncio
import logging
from src.server.server import start_chia_server
from src.server.outbound_message import NodeType
from src.util.network import parse_host_port
from src import plotter

logging.basicConfig(format='Plotter %(name)-24s: %(levelname)-8s %(message)s', level=logging.INFO)


async def main():
    host, port = parse_host_port(plotter)
    server, _ = await start_chia_server(host, port, plotter, NodeType.FARMER)
    await server

asyncio.run(main())
