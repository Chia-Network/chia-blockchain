import asyncio
import logging
import sys
from queue import Queue
from typing import List, Optional
from src.full_node import FullNode
from src.server.server import start_chia_server, start_chia_client, global_connections
from src.util.network import parse_host_port
from src.server.outbound_message import NodeType
from src.types.peer_info import PeerInfo
from src.store.full_node_store import FullNodeStore
from src.blockchain import Blockchain
from src.ui.prompt_ui import FullNodeUI
from src.util.logging import initialize_logging


"""
Full node startup algorithm:
- Update peer list (?)
- Start server
- Sync
- If connected to farmer, send challenges
- If connected to timelord, send challenges
"""

log = logging.getLogger(__name__)
server_closed = False


async def main():
    log_queue: Queue = initialize_logging()

    # Create the store (DB) and full node instance
    store = FullNodeStore()
    await store.initialize()
    blockchain = Blockchain(store)
    await blockchain.initialize()
    await global_connections.initialize()

    full_node = FullNode(store, blockchain)
    waitable_tasks: List[asyncio.Task] = []
    sync_task: Optional[asyncio.Task] = None
    peer_tasks: List[asyncio.Task] = []

    def master_close_cb():
        log.info("Closing all connections...")
        waitable_tasks[0].cancel()
        if sync_task:
            sync_task.cancel()
        for task in peer_tasks:
            task.cancel()
        global server_closed
        server_closed = True
        log.info("Server closed.")
    host, port = parse_host_port(full_node)

    FullNodeUI(store, blockchain, global_connections, port, master_close_cb, log_queue)

    # Starts the full node server (which full nodes can connect to)
    server, client = await start_chia_server(host, port, full_node, NodeType.FULL_NODE, full_node.on_connect)
    connect_to_farmer = ("-f" in sys.argv)
    connect_to_timelord = ("-t" in sys.argv)
    waitable_tasks.append(server)

    for peer in full_node.config['initial_peers']:
        if not (host == peer['host'] and port == peer['port']):
            # TODO: check if not in blacklist
            peer_task = start_chia_client(PeerInfo(peer['host'], peer['port'], bytes.fromhex(peer['node_id'])),
                                          port, full_node, NodeType.FULL_NODE)
            peer_tasks.append(asyncio.create_task(peer_task))
    try:
        awaited = await asyncio.gather(*peer_tasks, return_exceptions=True)
    except Exception:
        quit()
    connected_tasks = [response[0] for response in awaited if not isinstance(response, asyncio.CancelledError)]
    waitable_tasks = waitable_tasks + connected_tasks
    if server_closed:
        quit()

    log.info(f"Connected to {len(connected_tasks)} peers.")

    async def perform_sync():
        try:
            async for msg in full_node.sync():
                client.push(msg)
        except Exception as e:
            log.info(f"Exception syncing {type(e)}: {e}")
            raise
    sync_task = asyncio.create_task(perform_sync())
    try:
        await sync_task
    except asyncio.CancelledError:
        quit()
    if connect_to_farmer:
        try:
            peer_info = PeerInfo(full_node.config['farmer_peer']['host'],
                                 full_node.config['farmer_peer']['port'],
                                 bytes.fromhex(full_node.config['farmer_peer']['node_id']))
            farmer_con_task, farmer_client = await start_chia_client(peer_info, port, full_node, NodeType.FARMER)
            async for msg in full_node.send_heads_to_farmers():
                log.error(f"Will send msg {msg}")
                farmer_client.push(msg)
            waitable_tasks.append(farmer_con_task)
        except asyncio.CancelledError:
            log.warning("Connection to farmer failed.")

    if connect_to_timelord:
        try:
            peer_info = PeerInfo(full_node.config['timelord_peer']['host'],
                                 full_node.config['timelord_peer']['port'],
                                 bytes.fromhex(full_node.config['timelord_peer']['node_id']))
            timelord_con_task, timelord_client = await start_chia_client(peer_info, port, full_node,
                                                                         NodeType.TIMELORD)
            async for msg in full_node.send_challenges_to_timelords():
                timelord_client.push(msg)
            waitable_tasks.append(timelord_con_task)
        except asyncio.CancelledError:
            log.warning("Connection to timelord failed.")

    try:
        await asyncio.gather(*waitable_tasks)
    except asyncio.CancelledError:
        quit()


asyncio.run(main())
