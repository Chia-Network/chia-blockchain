import asyncio
import logging
from src import full_node
from src.server.connection import PeerConnections
from src.server.server import start_chia_server, start_chia_client


logging.basicConfig(format='FullNode %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)
global_connections = PeerConnections()


async def main():
    farmer_con_task, farmer_client = await start_chia_client(full_node.farmer_ip, full_node.farmer_port,
                                                             full_node, "farmer")

    timelord_con_task, timelord_client = await start_chia_client(full_node.timelord_ip, full_node.timelord_port,
                                                                 full_node, "timelord")

    # Starts the full node server (which full nodes can connect to)
    server, _ = await start_chia_server("127.0.0.1", full_node.full_node_port, full_node, "full_node")

    # Sends the latest heads and PoT rates to farmers
    async for msg in full_node.send_heads_to_farmers():
        farmer_client.push(msg)
    async for msg in full_node.send_challenges_to_timelords():
        timelord_client.push(msg)

    await asyncio.gather(farmer_con_task, timelord_con_task, server)

asyncio.run(main())
