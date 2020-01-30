import asyncio
import logging
import logging.config
import signal
from typing import List, Dict

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
from src.util.logging import initialize_logging
from src.util.config import load_config_cli
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
    config = load_config_cli("config.yaml", "full_node")

    # Create the store (DB) and full node instance
    store = await FullNodeStore.create(f"blockchain_{config['database_id']}.db")

    genesis: FullBlock = FullBlock.from_bytes(constants["GENESIS_BLOCK"])
    await store.add_block(genesis)

    log.info("Initializing blockchain from disk")
    small_header_blocks: Dict[
        str, SmallHeaderBlock
    ] = await load_header_blocks_from_store(store)
    blockchain = await Blockchain.create(small_header_blocks)

    full_node = FullNode(store, blockchain, config)

    if config["enable_upnp"]:
        log.info(f"Attempting to enable UPnP (open up port {config['port']})")
        try:
            upnp = miniupnpc.UPnP()
            upnp.discoverdelay = 5
            upnp.discover()
            upnp.selectigd()
            upnp.addportmapping(
                config["port"], "TCP", upnp.lanaddr, config["port"], "chia", ""
            )
            log.info(f"Port {config['port']} opened with UPnP.")
        except Exception as e:
            log.warning(f"UPnP failed: {e}")

    # Starts the full node server (which full nodes can connect to)
    server = ChiaServer(config["port"], full_node, NodeType.FULL_NODE)
    full_node._set_server(server)
    _ = await server.start_server(config["host"], full_node._on_connect)
    rpc_cleanup = None

    def master_close_cb():
        global server_closed
        if not server_closed:
            # Called by the UI, when node is closed, or when a signal is sent
            log.info("Closing all connections, and server...")
            full_node._shutdown()
            server.close_all()
            server_closed = True

    if config["start_rpc_server"]:
        # Starts the RPC server if -r is provided
        rpc_cleanup = await start_rpc_server(
            full_node, master_close_cb, config["rpc_port"]
        )

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, master_close_cb)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, master_close_cb)

    full_node._start_bg_tasks()

    log.info("Waiting to connect to some peers...")
    await asyncio.sleep(3)
    log.info(f"Connected to {len(server.global_connections.get_connections())} peers.")

    if config["connect_to_farmer"] and not server_closed:
        peer_info = PeerInfo(
            full_node.config["farmer_peer"]["host"],
            full_node.config["farmer_peer"]["port"],
        )
        _ = await server.start_client(peer_info, None)

    if config["connect_to_timelord"] and not server_closed:
        peer_info = PeerInfo(
            full_node.config["timelord_peer"]["host"],
            full_node.config["timelord_peer"]["port"],
        )
        _ = await server.start_client(peer_info, None)

    # Awaits for server and all connections to close
    await server.await_closed()
    log.info("Closed all node servers.")

    # Waits for the rpc server to close
    if rpc_cleanup is not None:
        await rpc_cleanup()
    log.info("Closed RPC server.")

    await store.close()
    log.info("Closed store.")

    await asyncio.get_running_loop().shutdown_asyncgens()
    log.info("Node fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
