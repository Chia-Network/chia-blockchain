import asyncio
import logging
from src import full_node
from src.server.server import start_server, retry_connection
from src.server.peer_connections import PeerConnections


logging.basicConfig(format='FullNode %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)
global_connections = PeerConnections()


async def main():
    farmer_con_fut = retry_connection(full_node, full_node.farmer_ip, full_node.farmer_port,
                                      "farmer", global_connections)

    timelord_con_fut = retry_connection(full_node, full_node.timelord_ip, full_node.timelord_port,
                                        "timelord", global_connections)
    # Starts the full node server (which full nodes can connect to)
    server = asyncio.create_task(start_server(full_node, '127.0.0.1',
                                              full_node.full_node_port, global_connections,
                                              "full_node"))

    # Both connections to farmer and timelord have been started
    await asyncio.gather(farmer_con_fut, timelord_con_fut)

    # Sends the latest heads and PoT rates to farmers
    farmer_update = full_node.send_heads_to_farmers(global_connections)
    timelord_update = full_node.send_challenges_to_timelords(global_connections)

    # Waits as long as the server is active
    await asyncio.gather(farmer_update, timelord_update, server)

asyncio.run(main())
