import asyncio
import logging
from src.server.server import start_chia_server
from src.server.connection import PeerConnections
from src import timelord

global_connections = PeerConnections()

logging.basicConfig(format='Timelord %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)


async def main():
    server, _ = await start_chia_server("127.0.0.1", timelord.timelord_port, timelord, "full_node")
    await server

asyncio.run(main())
