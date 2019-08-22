import asyncio
import logging

from src import farmer
from src.server.server import start_chia_client, start_chia_server
from src.server.connection import PeerConnections
from src.protocols.plotter_protocol import PlotterHandshake
from src.server.outbound_message import OutboundMessage

logging.basicConfig(format='Farmer %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)

global_connections = PeerConnections()


async def main():
    plotter_con_task, plotter_client = await start_chia_client(farmer.plotter_ip, farmer.plotter_port, farmer,
                                                               "plotter")

    # Sends a handshake to the plotter
    msg = PlotterHandshake([sk.get_public_key() for sk in farmer.db.pool_sks])
    plotter_client.push(OutboundMessage("plotter", "plotter_handshake", msg, True, True))

    # Starts the farmer server (which full nodes can connect to)
    server, _ = await start_chia_server("127.0.0.1", farmer.farmer_port, farmer, "full_node")

    await asyncio.gather(plotter_con_task, server)

asyncio.run(main())
