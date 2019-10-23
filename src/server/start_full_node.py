import asyncio
import logging
import sys
from typing import List, Callable
from src.full_node import FullNode
from src.server.server import start_chia_server, start_chia_client
from src.util.network import parse_host_port
from src.server.outbound_message import NodeType
from src.types.peer_info import PeerInfo
from src.store.full_node_store import FullNodeStore
from src.blockchain import Blockchain
from src.ui.full_node_ui import start_ui


logging.basicConfig(format='FullNode %(name)-23s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s',
                    level=logging.INFO,
                    datefmt='%H:%M:%S'
                    )
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
    # Create the store (DB) and full node instance
    close_callbacks: List[Callable] = []
    store = FullNodeStore()
    await store.initialize()
    blockchain = Blockchain(store)
    await blockchain.initialize()

    full_node = FullNode(store, blockchain)

    # TODO: improve this, remove errors
    def master_close_cb():
        for cb in close_callbacks:
            cb()
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

        [task.cancel() for task in tasks]

    start_ui(store, blockchain, master_close_cb)

    # Starts the full node server (which full nodes can connect to)
    host, port = parse_host_port(full_node)
    server, client, close_cb = await start_chia_server(host, port, full_node, NodeType.FULL_NODE, full_node.on_connect)
    close_callbacks.append(close_cb)
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
    close_callbacks = close_callbacks + [response[2] for response in awaited
                                         if not isinstance(response, asyncio.CancelledError)]
    waitable_tasks = waitable_tasks + connected_tasks
    log.info(f"Connected to {len(connected_tasks)} peers.")

    try:
        async for msg in full_node.sync():
            client.push(msg)
    except BaseException as e:
        log.info(f"Error syncing {e}")
        raise

    if connect_to_farmer:
        try:
            peer_info = PeerInfo(full_node.config['farmer_peer']['host'],
                                 full_node.config['farmer_peer']['port'],
                                 bytes.fromhex(full_node.config['farmer_peer']['node_id']))
            farmer_con_task, farmer_client, close_cb = await start_chia_client(peer_info, full_node, NodeType.FARMER)
            close_callbacks.append(close_cb)
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
            timelord_con_task, timelord_client, close_cb = await start_chia_client(peer_info, full_node,
                                                                                   NodeType.TIMELORD)
            close_callbacks.append(close_cb)
            async for msg in full_node.send_challenges_to_timelords():
                timelord_client.push(msg)
            waitable_tasks.append(timelord_con_task)
        except asyncio.CancelledError:
            log.warning("Connection to timelord failed.")

    await asyncio.gather(*waitable_tasks, return_exceptions=True)


asyncio.run(main())
