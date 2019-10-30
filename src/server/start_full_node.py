import asyncio
import logging
import sys
from typing import Optional
from src.full_node import FullNode
from src.server.server import ChiaServer
from src.util.network import parse_host_port
from src.server.outbound_message import NodeType
from src.types.peer_info import PeerInfo
from src.store.full_node_store import FullNodeStore
from src.blockchain import Blockchain
from src.ui.prompt_ui import FullNodeUI


"""
Full node startup algorithm:
- Update peer list (?)
- Start server
- Sync
- If connected to farmer, send challenges
- If connected to timelord, send challenges
"""

logging.basicConfig(format='FullNode %(name)-23s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s',
                    level=logging.INFO,
                    datefmt='%H:%M:%S'
                    )

log = logging.getLogger(__name__)
server_closed = False


async def main():
    # Create the store (DB) and full node instance
    store = FullNodeStore()
    await store.initialize()
    blockchain = Blockchain(store)
    await blockchain.initialize()

    full_node = FullNode(store, blockchain)
    # Starts the full node server (which full nodes can connect to)
    host, port = parse_host_port(full_node)
    server = ChiaServer(port, full_node, NodeType.FULL_NODE)
    _ = await server.start_server(host, NodeType.FULL_NODE, full_node.on_connect)
    ui: Optional[FullNodeUI] = None

    def master_close_cb():
        log.info("Closing all connections...")
        server.close_all()
        global server_closed
        server_closed = True
        log.info("Server closed.")

    if "-u" in sys.argv:
        ui = FullNodeUI(store, blockchain, server.global_connections, port, full_node.config['ssh_port'],
                        full_node.config['ssh_filename'], master_close_cb)

    connect_to_farmer = ("-f" in sys.argv)
    connect_to_timelord = ("-t" in sys.argv)

    peer_tasks = []
    for peer in full_node.config['initial_peers']:
        if not (host == peer['host'] and port == peer['port']):
            peer_tasks.append(server.start_client(PeerInfo(peer['host'], peer['port'], bytes.fromhex(peer['node_id'])),
                                                  NodeType.FULL_NODE, full_node.on_connect))
    await asyncio.gather(*peer_tasks)

    log.info("Waiting to perform handshake with all peers...")
    # TODO: have a cleaner way to wait for all the handshakes
    await asyncio.sleep(3)
    if server_closed:
        return

    async with server.global_connections.get_lock():
        log.info(f"Connected to {len(await server.global_connections.get_connections())} peers.")

    async for msg in full_node.sync():
        server.push_message(msg)

    if connect_to_farmer:
        peer_info = PeerInfo(full_node.config['farmer_peer']['host'],
                             full_node.config['farmer_peer']['port'],
                             bytes.fromhex(full_node.config['farmer_peer']['node_id']))
        _ = await server.start_client(peer_info, NodeType.FARMER, full_node.send_heads_to_farmers)

    if connect_to_timelord:
        peer_info = PeerInfo(full_node.config['timelord_peer']['host'],
                             full_node.config['timelord_peer']['port'],
                             bytes.fromhex(full_node.config['timelord_peer']['node_id']))
        _ = await server.start_client(peer_info, NodeType.TIMELORD, full_node.send_challenges_to_timelords)

    await server.await_closed()
    if ui is not None:
        await ui.await_closed()


asyncio.run(main())
