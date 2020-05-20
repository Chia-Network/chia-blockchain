import asyncio
import signal
import logging

try:
    import uvloop
except ImportError:
    uvloop = None

from src.harvester import Harvester
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo
from src.util.config import load_config, load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.rpc.harvester_rpc_server import start_harvester_rpc_server
from src.util.logging import initialize_logging
from src.util.setproctitle import setproctitle


def start_harvester_bg_task(server, peer_info, log):
    """
    Start a background task that checks connection and reconnects periodically to the farmer.
    """

    async def connection_check():
        while True:
            farmer_retry = True

            for (
                connection
            ) in server.global_connections.get_connections():
                if connection.get_peer_info() == peer_info:
                    farmer_retry = False

            if farmer_retry:
                log.info(f"Reconnecting to farmer {farmer_retry}")
                if not await server.start_client(
                    peer_info, None, auth=True
                ):
                    await asyncio.sleep(1)
            await asyncio.sleep(1)

    return asyncio.create_task(connection_check())


async def async_main():
    root_path = DEFAULT_ROOT_PATH
    net_config = load_config(root_path, "config.yaml")
    config = load_config_cli(root_path, "config.yaml", "harvester")
    try:
        plot_config = load_config(root_path, "plots.yaml")
    except FileNotFoundError:
        raise RuntimeError("Plots not generated. Run chia-create-plots")

    initialize_logging("Harvester %(name)-22s", config["logging"], root_path)
    log = logging.getLogger(__name__)
    setproctitle("chia_harvester")

    harvester = await Harvester.create(config, plot_config, root_path)
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")
    assert ping_interval is not None
    assert network_id is not None
    server = ChiaServer(
        config["port"],
        harvester,
        NodeType.HARVESTER,
        ping_interval,
        network_id,
        DEFAULT_ROOT_PATH,
        config,
    )

    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)
    except NotImplementedError:
        log.info("signal handlers unsupported")

    rpc_cleanup = None
    if config["start_rpc_server"]:
        # Starts the RPC server
        rpc_cleanup = await start_harvester_rpc_server(
            harvester, server.close_all, config["rpc_port"]
        )

    harvester.set_server(server)
    await asyncio.sleep(1)
    peer_info = PeerInfo(
        config["farmer_peer"]["host"], config["farmer_peer"]["port"]
    )
    farmer_bg_task = start_harvester_bg_task(server, peer_info, log)

    await server.await_closed()
    harvester._shutdown()
    await harvester._await_shutdown()

    # Waits for the rpc server to close
    if rpc_cleanup is not None:
        await rpc_cleanup()
    log.info("Closed RPC server.")

    farmer_bg_task.cancel()
    log.info("Harvester fully closed.")


def main():
    if uvloop is not None:
        uvloop.install()
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
