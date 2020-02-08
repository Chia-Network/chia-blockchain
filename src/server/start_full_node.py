import asyncio
import logging
import logging.config
import signal
from pathlib import Path

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
from src.mempool_manager import MempoolManager
from src.server.server import ChiaServer
from src.server.connection import NodeType
from src.types.full_block import FullBlock
from src.types.peer_info import PeerInfo
from src.coin_store import CoinStore
from src.util.logging import initialize_logging
from src.util.config import load_config_cli
from setproctitle import setproctitle


async def main():
    config = load_config_cli("config.yaml", "full_node")
    setproctitle("chia_full_node")
    initialize_logging("FullNode %(name)-23s", config["logging"])

    log = logging.getLogger(__name__)
    server_closed = False

    db_path = Path(config["database_path"])

    # Create the store (DB) and full node instance
    store = await FullNodeStore.create(db_path)

    genesis: FullBlock = FullBlock.from_bytes(constants["GENESIS_BLOCK"])
    await store.add_block(genesis)
    unspent_store = await CoinStore.create(db_path)

    log.info("Initializing blockchain from disk")
    blockchain = await Blockchain.create(unspent_store, store)

    mempool_manager = MempoolManager(unspent_store)
    # await mempool.initialize() TODO uncomment once it's implemented

    full_node = FullNode(store, blockchain, config, mempool_manager, unspent_store)
    # Starts the full node server (which full nodes can connect to)

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
        nonlocal server_closed
        if not server_closed:
            # Called by the UI, when node is closed, or when a signal is sent
            log.info("Closing all connections, and server...")
            full_node._shutdown()
            server.close_all()
            server_closed = True

    if config["start_rpc_server"]:
        # Starts the RPC server
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
