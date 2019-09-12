import asyncio
import logging
from src.server.server import start_chia_server
from src import timelord
from src.util.network import parse_host_port

logging.basicConfig(format='Timelord %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)


async def main():
    host, port = parse_host_port(timelord)
    server, _ = await start_chia_server(host, port, timelord, "full_node")
    await server

asyncio.run(main())
