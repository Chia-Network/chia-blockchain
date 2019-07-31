import asyncio
import logging

from src import farmer
from src.server.server import start_server
from src.server.chia_connection import ChiaConnection
from src.server.peer_connections import PeerConnections
from src.protocols.plotter_protocol import PlotterHandshake

logging.basicConfig(format='Farmer %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)

global_connections = PeerConnections()


async def main():
    client_con = ChiaConnection(farmer, global_connections)
    total_time: int = 0
    succeeded: bool = False
    while total_time < 20 and not succeeded:
        try:
            client_con = ChiaConnection(farmer, global_connections, "plotter")
            await client_con.open_connection(farmer.plotter_ip, farmer.plotter_port)
            succeeded = True
        except ConnectionRefusedError:
            print(f"Connection to {farmer.plotter_ip}:{farmer.plotter_port} refused.")
            await asyncio.sleep(5)
        total_time += 5
    if not succeeded:
        raise TimeoutError("Failed to connect to plotter.")

    # Sends a handshake to the plotter
    await client_con.send("plotter_handshake",
                          PlotterHandshake([sk.get_public_key() for sk in farmer.db.pool_sks]))
    # Starts the farmer server (which full nodes can connect to)
    await start_server(farmer, '127.0.0.1', farmer.farmer_port, global_connections, "full_node")

asyncio.run(main())
