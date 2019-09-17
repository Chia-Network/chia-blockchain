import asyncio
import logging

from src import farmer
from src.server.server import start_chia_client, start_chia_server
from src.protocols.plotter_protocol import PlotterHandshake
from src.server.outbound_message import OutboundMessage, Message, Delivery, NodeType
from src.util.network import parse_host_port

logging.basicConfig(format='Farmer %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)


async def main():
    plotter_con_task, plotter_client = await start_chia_client(farmer.plotter_peer,
                                                               farmer, NodeType.PLOTTER)

    # Sends a handshake to the plotter
    msg = PlotterHandshake([sk.get_public_key() for sk in farmer.db.pool_sks])
    plotter_client.push(OutboundMessage(NodeType.PLOTTER, Message("plotter_handshake", msg), Delivery.BROADCAST))

    # Starts the farmer server (which full nodes can connect to)
    host, port = parse_host_port(farmer)
    server, _ = await start_chia_server(host, port, farmer, NodeType.FULL_NODE)

    await asyncio.gather(plotter_con_task, server)

asyncio.run(main())
