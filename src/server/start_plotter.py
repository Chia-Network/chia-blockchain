import asyncio
import logging
from src.server.server import start_server
from src.server.peer_connections import PeerConnections
from src import plotter

global_connections = PeerConnections()

logging.basicConfig(format='Plotter %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)
asyncio.run(start_server(plotter, '127.0.0.1', plotter.plotter_port, global_connections, "farmer"))
