import asyncio
from src.server.server import start_server
from src import plotter

asyncio.run(start_server(plotter, '127.0.0.1', 8000))
