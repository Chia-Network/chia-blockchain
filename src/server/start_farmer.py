import asyncio
import logging
from typing import List
from blspy import PrivateKey
from src.farmer import Farmer
from src.types.peer_info import PeerInfo
from src.server.server import ChiaServer
from src.protocols.plotter_protocol import PlotterHandshake
from src.server.outbound_message import OutboundMessage, Message, Delivery, NodeType
from src.util.network import parse_host_port

logging.basicConfig(format='Farmer %(name)-25s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s',
                    level=logging.INFO,
                    datefmt='%H:%M:%S'
                    )


async def main():
    farmer = Farmer()
    plotter_peer = PeerInfo(farmer.config['plotter_peer']['host'],
                            farmer.config['plotter_peer']['port'],
                            bytes.fromhex(farmer.config['plotter_peer']['node_id']))
    host, port = parse_host_port(farmer)
    server = ChiaServer(port=port, api=farmer, connection_type=NodeType.PLOTTER)
    _ = await server.start(host)
    # plotter_con_task, plotter_client = await server.start(host, None, )
    # plotter_con_task, plotter_client = await start_chia_client(plotter_peer, port, farmer, NodeType.PLOTTER)

    _ = await server.connect_to(plotter_peer)

    # Sends a handshake to the plotter
    pool_sks: List[PrivateKey] = [PrivateKey.from_bytes(bytes.fromhex(ce)) for ce in farmer.config["pool_sks"]]
    msg = PlotterHandshake([sk.get_public_key() for sk in pool_sks])

    server.process_message(OutboundMessage(NodeType.PLOTTER, Message("plotter_handshake", msg),
                           Delivery.BROADCAST))

    # Starts the farmer server (which full nodes can connect to)
    server, _ = await start_chia_server(host, port, farmer, NodeType.FULL_NODE)

    await asyncio.gather(plotter_con_task, server)

asyncio.run(main())
