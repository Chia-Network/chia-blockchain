import asyncio
import logging
from src.server.server import start_chia_server
from src import plotter
from src.util.network import parse_host_port

logging.basicConfig(format='Plotter %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)


async def main():
    host, port = parse_host_port(plotter)
    server, _ = await start_chia_server(host, port, plotter, "farmer")
    await server

asyncio.run(main())
