import asyncio
import logging
from src.server.server import start_chia_server
from src.server.connection import PeerConnections
from src import plotter

global_connections = PeerConnections()

logging.basicConfig(format='Plotter %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)


async def main():
    server, _ = await start_chia_server("127.0.0.1", plotter.plotter_port, plotter, "farmer")
    await server

asyncio.run(main())
