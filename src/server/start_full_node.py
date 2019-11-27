import asyncio
import logging
import signal
import sys
import miniupnpc

from src.blockchain import Blockchain
from src.database import FullNodeStore
from src.full_node import FullNode

# from src.util.ints import uint16
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer

# from src.server.local_api_server import FullNodeLocalApi
from src.types.peer_info import PeerInfo
from src.util.network import parse_host_port

logging.basicConfig(
    format="FullNode %(name)-23s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)

log = logging.getLogger(__name__)
server_closed = False


async def main():
    # Create the store (DB) and full node instance
    db_id = 0
    if "-id" in sys.argv:
        db_id = int(sys.argv[sys.argv.index("-id") + 1])
    store = FullNodeStore(f"fndb_{db_id}")

    blockchain = Blockchain(store)
    log.info("Initializing blockchain from disk")
    await blockchain.initialize()

    full_node = FullNode(store, blockchain)
    # Starts the full node server (which full nodes can connect to)
    host, port = parse_host_port(full_node)

    if full_node.config["enable_upnp"]:
        log.info(f"Attempting to enable UPnP (open up port {port})")
        try:
            upnp = miniupnpc.UPnP()
            upnp.discoverdelay = 5
            upnp.discover()
            upnp.selectigd()
            upnp.addportmapping(port, "TCP", upnp.lanaddr, port, "chia", "")
        except Exception as e:
            log.warning(f"UPnP failed: {e}")

    server = ChiaServer(port, full_node, NodeType.FULL_NODE)
    full_node._set_server(server)
    _ = await server.start_server(host, full_node._on_connect)
    wait_for_ui, ui_close_cb = None, None

    def master_close_cb():
        # Called by the UI, when node is closed, or when a signal is sent
        log.info("Closing all connections, and server...")
        full_node._shutdown()
        server.close_all()
        global server_closed
        server_closed = True

    def signal_received():
        if ui_close_cb:
            ui_close_cb()
        master_close_cb()

    # local_api_server = FullNodeLocalApi(blockchain, store, server, master_close_cb, uint16(8080))
    # await local_api_server.start()

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, signal_received)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, signal_received)

    if "-u" in sys.argv:
        # Starts the UI if -u is provided
        index = sys.argv.index("-u")
        ui_ssh_port = int(sys.argv[index + 1])
        from src.ui.prompt_ui import start_ssh_server

        wait_for_ui, ui_close_cb = start_ssh_server(
            store,
            blockchain,
            server,
            port,
            ui_ssh_port,
            full_node.config["ssh_filename"],
            master_close_cb,
        )

    connect_to_farmer = "-f" in sys.argv
    connect_to_timelord = "-t" in sys.argv

    full_node._start_bg_tasks()

    log.info("Waiting to connect to some peers...")
    await asyncio.sleep(3)
    log.info(f"Connected to {len(server.global_connections.get_connections())} peers.")

    if connect_to_farmer and not server_closed:
        peer_info = PeerInfo(
            full_node.config["farmer_peer"]["host"],
            full_node.config["farmer_peer"]["port"],
        )
        _ = await server.start_client(peer_info, None)

    if connect_to_timelord and not server_closed:
        peer_info = PeerInfo(
            full_node.config["timelord_peer"]["host"],
            full_node.config["timelord_peer"]["port"],
        )
        _ = await server.start_client(peer_info, None)

    # Awaits for server and all connections to close
    await server.await_closed()
    # await local_api_server.close()

    # Awaits for all ui instances to close
    if wait_for_ui is not None:
        await wait_for_ui()
    await asyncio.get_running_loop().shutdown_asyncgens()


# asyncio.run(main())
FullNodeStore.loop.run_until_complete(main())
