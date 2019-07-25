import asyncio
import logging
from src.server.server import start_server
from src import plotter

logging.basicConfig(format='Plotter %(name)-12s: %(levelname)-8s %(message)s', level=logging.INFO)
asyncio.run(start_server(plotter, '127.0.0.1', 8000))
