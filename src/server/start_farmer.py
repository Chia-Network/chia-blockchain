import asyncio
import logging
from typing import List
from blspy import PrivateKey
from src import farmer
from src.types.peer_info import PeerInfo
from src.server.server import start_chia_client, start_chia_server
from src.protocols.plotter_protocol import PlotterHandshake
from src.server.outbound_message import OutboundMessage, Message, Delivery, NodeType
from src.util.network import parse_host_port

logging.basicConfig(format='Farmer %(name)-25s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s',
                    level=logging.INFO,
                    datefmt='%H:%M:%S'
                    )


async def main():
    plotter_peer = PeerInfo(farmer.config['plotter_peer']['host'],
                            farmer.config['plotter_peer']['port'],
                            bytes.fromhex(farmer.config['plotter_peer']['node_id']))
    plotter_con_task, plotter_client = await start_chia_client(plotter_peer, farmer, NodeType.PLOTTER)

    # Sends a handshake to the plotter
    pool_sks: List[PrivateKey] = [PrivateKey.from_bytes(bytes.fromhex(ce)) for ce in farmer.config["pool_sks"]]
    msg = PlotterHandshake([sk.get_public_key() for sk in pool_sks])
    plotter_client.push(OutboundMessage(NodeType.PLOTTER, Message("plotter_handshake", msg), Delivery.BROADCAST))

    # Starts the farmer server (which full nodes can connect to)
    host, port = parse_host_port(farmer)
    server, _ = await start_chia_server(host, port, farmer, NodeType.FULL_NODE)

    await asyncio.gather(plotter_con_task, server)

asyncio.run(main())
