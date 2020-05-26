import asyncio
import logging
import logging.config
import signal
from src.simulator.full_node_simulator import FullNodeSimulator
from src.simulator.simulator_constants import test_constants

try:
    import uvloop
except ImportError:
    uvloop = None

from src.rpc.full_node_rpc_server import start_full_node_rpc_server
from src.server.server import ChiaServer
from src.server.connection import NodeType
from src.util.logging import initialize_logging
from src.util.config import load_config_cli, load_config
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.setproctitle import setproctitle
from src.util.path import mkdir, path_from_root


async def main():
    root_path = DEFAULT_ROOT_PATH
    net_config = load_config(root_path, "config.yaml")
    config = load_config_cli(root_path, "config.yaml", "full_node")
    setproctitle("chia_full_node_simulator")
    initialize_logging("FullNode %(name)-23s", config["logging"], root_path)

    log = logging.getLogger(__name__)
    server_closed = False

    db_path = path_from_root(root_path, config["simulator_database_path"])
    mkdir(db_path.parent)

    config["database_path"] = config["simulator_database_path"]
    full_node = await FullNodeSimulator.create(
        config, root_path=root_path, override_constants=test_constants,
    )

    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")

    # Starts the full node server (which full nodes can connect to)
    assert ping_interval is not None
    assert network_id is not None
    server = ChiaServer(
        config["port"],
        full_node,
        NodeType.FULL_NODE,
        ping_interval,
        network_id,
        DEFAULT_ROOT_PATH,
        config,
    )
    full_node._set_server(server)
    _ = await server.start_server(full_node._on_connect)
    rpc_cleanup = None

    def master_close_cb():
        nonlocal server_closed
        if not server_closed:
            # Called by the UI, when node is closed, or when a signal is sent
            log.info("Closing all connections, and server...")
            server.close_all()
            server_closed = True

        # Starts the RPC server

    rpc_cleanup = await start_full_node_rpc_server(
        full_node, master_close_cb, config["rpc_port"]
    )

    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, master_close_cb)
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, master_close_cb)
    except NotImplementedError:
        log.info("signal handlers unsupported")

    # Awaits for server and all connections to close
    await server.await_closed()
    log.info("Closed all node servers.")

    # Stops the full node and closes DBs
    await full_node._await_closed()

    # Waits for the rpc server to close
    if rpc_cleanup is not None:
        await rpc_cleanup()
    log.info("Closed RPC server.")

    await asyncio.get_running_loop().shutdown_asyncgens()
    log.info("Node fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
