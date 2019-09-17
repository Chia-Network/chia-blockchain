import asyncio
import logging
from src import full_node
import sys
from src.server.server import start_chia_server, start_chia_client
from src.util.network import parse_host_port
from src.server.outbound_message import NodeType
from src.types.peer_info import PeerInfo


logging.basicConfig(format='FullNode %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)

"""
Full node startup algorithm:
- Update peer list (?)
- Start server
- Sync
- If connected to farmer, send challenges
- If connected to timelord, send challenges
"""


async def main():
    # Starts the full node server (which full nodes can connect to)
    host, port = parse_host_port(full_node)
    server, client = await start_chia_server(host, port, full_node, NodeType.FULL_NODE, full_node.on_connect)
    connect_to_farmer = ("-f" in sys.argv)
    connect_to_timelord = ("-t" in sys.argv)

    waitable_tasks = [server]

    peer_tasks = []
    for peer in full_node.config['initial_peers']:
        if not (host == peer['host'] and port == peer['port']):
            # TODO: check if not in blacklist
            peer_task = start_chia_client(PeerInfo(peer['host'], peer['port'], bytes.fromhex(peer['node_id'])),
                                          full_node, NodeType.FULL_NODE)
            peer_tasks.append(peer_task)
    awaited = await asyncio.gather(*peer_tasks, return_exceptions=True)
    connected_tasks = [response[0] for response in awaited if not isinstance(response, asyncio.CancelledError)]
    waitable_tasks = waitable_tasks + connected_tasks
    log.info(f"Connected to {len(connected_tasks)} peers.")

    async for msg in full_node.sync():
        client.push(msg)

    if connect_to_farmer:
        try:
            peer_info = PeerInfo(full_node.config['farmer_peer']['host'],
                                 full_node.config['farmer_peer']['port'],
                                 bytes.fromhex(full_node.config['farmer_peer']['node_id']))
            farmer_con_task, farmer_client = await start_chia_client(peer_info, full_node, NodeType.FARMER)
            async for msg in full_node.send_heads_to_farmers():
                farmer_client.push(msg)
            waitable_tasks.append(farmer_con_task)
        except asyncio.CancelledError:
            log.warning("Connection to farmer failed.")

    if connect_to_timelord:
        try:
            peer_info = PeerInfo(full_node.config['timelord_peer']['host'],
                                 full_node.config['timelord_peer']['port'],
                                 bytes.fromhex(full_node.config['timelord_peer']['node_id']))
            timelord_con_task, timelord_client = await start_chia_client(peer_info, full_node, NodeType.TIMELORD)
            async for msg in full_node.send_challenges_to_timelords():
                timelord_client.push(msg)
            waitable_tasks.append(timelord_con_task)
        except asyncio.CancelledError:
            log.warning("Connection to timelord failed.")

    # Periodically update our estimate of proof of time speeds
    asyncio.create_task(full_node.proof_of_time_estimate_interval())

    await asyncio.gather(*waitable_tasks)

asyncio.run(main())
