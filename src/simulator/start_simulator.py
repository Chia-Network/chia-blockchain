import asyncio
import logging
import logging.config
import signal
import aiosqlite
from src.simulator.full_node_simulator import FullNodeSimulator
from src.simulator.simulator_constants import test_constants

try:
    import uvloop
except ImportError:
    uvloop = None

from src.full_node.blockchain import Blockchain
from src.full_node.store import FullNodeStore
from src.rpc.rpc_server import start_rpc_server
from src.full_node.mempool_manager import MempoolManager
from src.server.server import ChiaServer
from src.server.connection import NodeType
from src.types.full_block import FullBlock
from src.full_node.coin_store import CoinStore
from src.util.logging import initialize_logging
from src.util.config import load_config_cli
from src.util.setproctitle import setproctitle
from src.util.path import mkdir, path_from_root


async def main():
    config = load_config_cli("config.yaml", "full_node")
    setproctitle("chia_full_node")
    initialize_logging("FullNode %(name)-23s", config["logging"])

    log = logging.getLogger(__name__)
    server_closed = False

    db_path = path_from_root(config["simulator_database_path"])
    mkdir(db_path.parent)
    connection = await aiosqlite.connect(db_path)

    # Create the store (DB) and full node instance
    store = await FullNodeStore.create(connection)
    await store._clear_database()

    genesis: FullBlock = FullBlock.from_bytes(test_constants["GENESIS_BLOCK"])
    await store.add_block(genesis)
    unspent_store = await CoinStore.create(connection)

    log.info("Initializing blockchain from disk")
    blockchain = await Blockchain.create(unspent_store, store, test_constants)

    mempool_manager = MempoolManager(unspent_store, test_constants)
    await mempool_manager.new_tips(await blockchain.get_full_tips())

    full_node = FullNodeSimulator(
        store,
        blockchain,
        config,
        mempool_manager,
        unspent_store,
        override_constants=test_constants,
    )

    # Starts the full node server (which full nodes can connect to)
    server = ChiaServer(config["port"], full_node, NodeType.FULL_NODE)
    full_node._set_server(server)
    _ = await server.start_server(config["host"], full_node._on_connect, config)
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

    log.info("Waiting to connect to some peers...")
    await asyncio.sleep(3)
    log.info(f"Connected to {len(server.global_connections.get_connections())} peers.")

    # Awaits for server and all connections to close
    await server.await_closed()
    log.info("Closed all node servers.")

    # Waits for the rpc server to close
    if rpc_cleanup is not None:
        await rpc_cleanup()
    log.info("Closed RPC server.")

    await store.close()
    log.info("Closed store.")

    await unspent_store.close()
    log.info("Closed unspent store.")

    await asyncio.get_running_loop().shutdown_asyncgens()
    log.info("Node fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
