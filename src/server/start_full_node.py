import asyncio
import logging
import logging.config
import signal
import sys
from typing import Dict, List

import miniupnpc

try:
    import uvloop
except ImportError:
    uvloop = None

from src.blockchain import Blockchain
from src.consensus.constants import constants
from src.store import FullNodeStore
from src.full_node import FullNode
from src.rpc.rpc_server import start_rpc_server
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.types.full_block import FullBlock
from src.types.header_block import SmallHeaderBlock
from src.types.peer_info import PeerInfo
from src.util.network import parse_host_port
from src.util.logging import initialize_logging
from setproctitle import setproctitle

setproctitle("chia_full_node")
initialize_logging("FullNode %(name)-23s")
log = logging.getLogger(__name__)

server_closed = False


async def load_header_blocks_from_store(
    store: FullNodeStore,
) -> Dict[str, SmallHeaderBlock]:
    seen_blocks: Dict[str, SmallHeaderBlock] = {}
    tips: List[SmallHeaderBlock] = []
    for small_header_block in await store.get_small_header_blocks():
        if not tips or small_header_block.weight > tips[0].weight:
            tips = [small_header_block]
        seen_blocks[small_header_block.header_hash] = small_header_block

    header_blocks = {}
    if len(tips) > 0:
        curr: SmallHeaderBlock = tips[0]
        reverse_blocks: List[SmallHeaderBlock] = [curr]
        while curr.height > 0:
            curr = seen_blocks[curr.prev_header_hash]
            reverse_blocks.append(curr)

        for block in reversed(reverse_blocks):
            header_blocks[block.header_hash] = block
    return header_blocks


async def main():
    # Create the store (DB) and full node instance
    db_id = 0
    if "-id" in sys.argv:
        db_id = int(sys.argv[sys.argv.index("-id") + 1])
    store = await FullNodeStore.create(f"blockchain_{db_id}.db")

    genesis: FullBlock = FullBlock.from_bytes(constants["GENESIS_BLOCK"])
    await store.add_block(genesis)

    log.info("Initializing blockchain from disk")
    small_header_blocks: Dict[
        str, SmallHeaderBlock
    ] = await load_header_blocks_from_store(store)
    blockchain = await Blockchain.create(small_header_blocks)

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
            log.info(f"Port {port} opened with UPnP.")
        except Exception as e:
            log.warning(f"UPnP failed: {e}")

    server = ChiaServer(port, full_node, NodeType.FULL_NODE)
    full_node._set_server(server)
    _ = await server.start_server(host, full_node._on_connect)
    rpc_cleanup = None

    def master_close_cb():
        global server_closed
        if not server_closed:
            # Called by the UI, when node is closed, or when a signal is sent
            log.info("Closing all connections, and server...")
            full_node._shutdown()
            server.close_all()
            server_closed = True

    if "-r" in sys.argv:
        # Starts the RPC server if -r is provided
        index = sys.argv.index("-r")
        rpc_port = int(sys.argv[index + 1])
        rpc_cleanup = await start_rpc_server(full_node, master_close_cb, rpc_port)

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, master_close_cb)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, master_close_cb)

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

    log.info(" 0 Closing ser")
    # Awaits for server and all connections to close
    await server.await_closed()
    log.info(" 1 Closing ser")

    # Waits for the rpc server to close
    if rpc_cleanup is not None:
        await rpc_cleanup()
    log.info(" 2 Closing ser")

    await store.close()
    log.info(" 3 Closing ser")
    await asyncio.get_running_loop().shutdown_asyncgens()
    log.info("Node fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
