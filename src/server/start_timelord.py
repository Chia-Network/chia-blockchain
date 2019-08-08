import asyncio
import logging
from src.server.server import start_server
from src.server.peer_connections import PeerConnections
from src import timelord

global_connections = PeerConnections()

logging.basicConfig(format='Timelord %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)
asyncio.run(start_server(timelord, '127.0.0.1', timelord.timelord_port, global_connections, "full_node"))
