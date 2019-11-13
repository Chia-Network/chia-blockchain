import asyncio
import logging
import sys
import signal
from src.full_node import FullNode
from src.server.server import ChiaServer
from src.util.network import parse_host_port
from src.server.outbound_message import NodeType
from src.types.peer_info import PeerInfo
from src.store.full_node_store import FullNodeStore
from src.blockchain import Blockchain


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
    _ = await server.start_server(host, full_node._on_connect)
    wait_for_ui, ui_close_cb = None, None

    def master_close_cb():
        # Called by the UI, when node is closed, or when a signal is sent
        log.info("Closing all connections, and server...")
        server.close_all()
        global server_closed
        server_closed = True

    def signal_received():
        if ui_close_cb:
            ui_close_cb()
        master_close_cb()
    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, signal_received)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, signal_received)

    if "-u" in sys.argv:
        # Starts the UI if -u is provided
        index = sys.argv.index("-u")
        ui_ssh_port = int(sys.argv[index + 1])
        from src.ui.prompt_ui import start_ssh_server
        wait_for_ui, ui_close_cb = start_ssh_server(store, blockchain, server, port, ui_ssh_port,
                                                    full_node.config['ssh_filename'], master_close_cb)

    connect_to_farmer = ("-f" in sys.argv)
    connect_to_timelord = ("-t" in sys.argv)

    peer_tasks = []
    for peer in full_node.config['initial_peers']:
        if not (host == peer['host'] and port == peer['port']):
            peer_tasks.append(server.start_client(PeerInfo(peer['host'], peer['port']),
                                                  None))
    await asyncio.gather(*peer_tasks)

    log.info("Waiting to connect to some peers...")
    await asyncio.sleep(3)

    log.info(f"Connected to {len(server.global_connections)} peers.")
    if not server_closed:
        try:
            async for msg in full_node._sync():
                if server_closed:
                    break
                server.push_message(msg)
        except BaseException as e:
            log.error(f"Error syncing {type(e)}: {e}")
            signal_received()

    if connect_to_farmer and not server_closed:
        peer_info = PeerInfo(full_node.config['farmer_peer']['host'],
                             full_node.config['farmer_peer']['port'])
        _ = await server.start_client(peer_info, None)
        async for msg in full_node._send_heads_to_farmers():
            if server_closed:
                break
            server.push_message(msg)

    if connect_to_timelord and not server_closed:
        peer_info = PeerInfo(full_node.config['timelord_peer']['host'],
                             full_node.config['timelord_peer']['port'])
        _ = await server.start_client(peer_info, None)
        async for msg in full_node._send_challenges_to_timelords():
            if server_closed:
                break
            server.push_message(msg)

    # Awaits for server and all connections to close
    await server.await_closed()

    # Awaits for all ui instances to close
    if wait_for_ui is not None:
        await wait_for_ui()
    await asyncio.get_running_loop().shutdown_asyncgens()


asyncio.run(main())
