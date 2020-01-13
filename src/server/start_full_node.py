import asyncio
import logging
import signal
import sys
from typing import Dict, List

import miniupnpc
import uvloop

from src.blockchain import Blockchain
from src.consensus.constants import constants
from src.store import FullNodeStore
from src.full_node import FullNode
from src.rpc.rpc_server import start_rpc_server
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.peer_info import PeerInfo
from src.util.network import parse_host_port
from setproctitle import setproctitle

logging.basicConfig(
    format="FullNode %(name)-23s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)
setproctitle("chia_full_node")

log = logging.getLogger(__name__)
server_closed = False


async def load_header_blocks_from_store(
    store: FullNodeStore,
) -> Dict[str, HeaderBlock]:
    seen_blocks: Dict[str, HeaderBlock] = {}
    tips: List[HeaderBlock] = []
    async for full_block in store.get_blocks():
        if not tips or full_block.weight > tips[0].weight:
            tips = [full_block.header_block]
        seen_blocks[full_block.header_hash] = full_block.header_block

    header_blocks = {}
    if len(tips) > 0:
        curr: HeaderBlock = tips[0]
        reverse_blocks: List[HeaderBlock] = [curr]
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
    store = await FullNodeStore.create(f"fndb_{db_id}.db")

    genesis: FullBlock = FullBlock.from_bytes(constants["GENESIS_BLOCK"])
    await store.add_block(genesis)

    log.info("Initializing blockchain from disk")
    header_blocks: Dict[str, HeaderBlock] = await load_header_blocks_from_store(store)
    blockchain = Blockchain()
    await blockchain.initialize(header_blocks)

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

    # Awaits for server and all connections to close
    await server.await_closed()

    # Waits for the rpc server to close
    if rpc_cleanup is not None:
        await rpc_cleanup()

    await store.close()
    blockchain.pool.shutdown()
    await asyncio.get_running_loop().shutdown_asyncgens()


uvloop.install()
asyncio.run(main())
