import asyncio
import logging
import logging.config
import signal
import miniupnpc

from typing import AsyncGenerator

try:
    import uvloop
except ImportError:
    uvloop = None

from src.full_node.full_node import FullNode
from src.protocols import introducer_protocol
from src.rpc.full_node_rpc_server import start_full_node_rpc_server
from src.server.server import ChiaServer, start_server
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.util.logging import initialize_logging
from src.util.config import load_config_cli, load_config
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.setproctitle import setproctitle
from multiprocessing import freeze_support

from src.types.peer_info import PeerInfo


OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]


def start_full_node_bg_task(
    server,
    peer_info,
    global_connections,
    introducer_connect_interval,
    target_peer_count,
):
    """

    Start a background task connecting periodically to the introducer and
    requesting the peer list.
    """

    def _num_needed_peers() -> int:
        diff = target_peer_count - len(global_connections.get_full_node_connections())
        return diff if diff >= 0 else 0

    async def introducer_client():
        async def on_connect() -> OutboundMessageGenerator:
            msg = Message("request_peers", introducer_protocol.RequestPeers())
            yield OutboundMessage(NodeType.INTRODUCER, msg, Delivery.RESPOND)

        while True:
            # If we are still connected to introducer, disconnect
            for connection in global_connections.get_connections():
                if connection.connection_type == NodeType.INTRODUCER:
                    global_connections.close(connection)
            # The first time connecting to introducer, keep trying to connect
            if _num_needed_peers():
                if not await server.start_client(peer_info, on_connect):
                    await asyncio.sleep(5)
                    continue
            await asyncio.sleep(introducer_connect_interval)

    return asyncio.create_task(introducer_client())


async def async_main():
    root_path = DEFAULT_ROOT_PATH
    config = load_config_cli(root_path, "config.yaml", "full_node")
    net_config = load_config(root_path, "config.yaml")
    setproctitle("chia_full_node")
    initialize_logging("FullNode %(name)-23s", config["logging"], root_path)

    log = logging.getLogger(__name__)
    server_closed = False

    full_node = await FullNode.create(config, root_path=root_path)

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
        except Exception:
            log.warning(
                "UPnP failed. This is not required to run chia, but it allows incoming connections from other peers."
            )

    # Starts the full node server (which full nodes can connect to)
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")
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
    _ = await start_server(server, full_node._on_connect)
    rpc_cleanup = None

    def master_close_cb():
        nonlocal server_closed
        if not server_closed:
            # Called by the UI, when node is closed, or when a signal is sent
            log.info("Closing all connections, and server...")
            server.close_all()
            full_node._close()
            server_closed = True

    if config["start_rpc_server"]:
        # Starts the RPC server
        rpc_cleanup = await start_full_node_rpc_server(
            full_node, master_close_cb, config["rpc_port"]
        )

    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, master_close_cb)
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, master_close_cb)
    except NotImplementedError:
        log.info("signal handlers unsupported")

    introducer = config["introducer_peer"]
    peer_info = PeerInfo(introducer["host"], introducer["port"])

    bg_task = start_full_node_bg_task(
        server,
        peer_info,
        server.global_connections,
        config["introducer_connect_interval"],
        config["target_peer_count"],
    )

    # Awaits for server and all connections to close
    await server.await_closed()
    log.info("Closed all node servers.")

    # Stops the full node and closes DBs
    await full_node._await_closed()
    bg_task.cancel()

    # Waits for the rpc server to close
    if rpc_cleanup is not None:
        await rpc_cleanup()
    log.info("Closed RPC server.")

    await asyncio.get_running_loop().shutdown_asyncgens()
    log.info("Node fully closed.")


def main():
    if uvloop is not None:
        uvloop.install()
    asyncio.run(async_main())


if __name__ == "__main__":
    freeze_support()
    main()
