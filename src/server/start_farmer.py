import asyncio
import signal
import logging

from src.util.keychain import Keychain

try:
    import uvloop
except ImportError:
    uvloop = None

from src.farmer import Farmer
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer, start_server
from src.types.peer_info import PeerInfo
from src.util.config import load_config, load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.logging import initialize_logging
from src.util.setproctitle import setproctitle
from src.rpc.farmer_rpc_server import start_farmer_rpc_server


def start_farmer_bg_task(server, peer_info, log):
    """
    Start a background task that checks connection and reconnects periodically to the full_node.
    """

    async def connection_check():
        while True:
            if server is not None:
                full_node_retry = True

                for connection in server.global_connections.get_connections():
                    if connection.get_peer_info() == peer_info:
                        full_node_retry = False

                if full_node_retry:
                    log.info(f"Reconnecting to full_node {peer_info}")
                    if not await server.start_client(peer_info, None, auth=False):
                        await asyncio.sleep(1)
            await asyncio.sleep(30)

    return asyncio.create_task(connection_check())


async def async_main():
    root_path = DEFAULT_ROOT_PATH
    net_config = load_config(root_path, "config.yaml")
    config = load_config_cli(root_path, "config.yaml", "farmer")

    # TOD: Remove once we have pool server
    config_pool = load_config_cli(root_path, "config.yaml", "pool")

    initialize_logging("Farmer %(name)-25s", config["logging"], root_path)
    log = logging.getLogger(__name__)
    setproctitle("chia_farmer")

    keychain = Keychain()

    farmer = Farmer(config, config_pool, keychain)

    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")
    assert ping_interval is not None
    assert network_id is not None
    server = ChiaServer(
        config["port"],
        farmer,
        NodeType.FARMER,
        ping_interval,
        network_id,
        root_path,
        config,
    )

    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)
    except NotImplementedError:
        log.info("signal handlers unsupported")

    _ = await start_server(server, farmer._on_connect)
    farmer.set_server(server)

    rpc_cleanup = None
    if config["start_rpc_server"]:
        # Starts the RPC server
        rpc_cleanup = await start_farmer_rpc_server(
            farmer, server.close_all, config["rpc_port"]
        )

    await asyncio.sleep(10)  # Allows full node to startup

    peer_info = PeerInfo(
        config["full_node_peer"]["host"], config["full_node_peer"]["port"]
    )
    farmer_bg_task = start_farmer_bg_task(server, peer_info, log)

    await server.await_closed()

    # Waits for the rpc server to close
    if rpc_cleanup is not None:
        await rpc_cleanup()
    log.info("Closed RPC server.")

    farmer._shut_down = True
    farmer_bg_task.cancel()
    log.info("Farmer fully closed.")


def main():
    if uvloop is not None:
        uvloop.install()
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
