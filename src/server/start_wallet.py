import asyncio
import signal
import logging
import websockets

from src.wallet.wallet_node import WalletNode

try:
    import uvloop
except ImportError:
    uvloop = None

from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.util.logging import initialize_logging
from src.util.config import load_config, load_config_cli
from src.wallet.websocket_server import WebSocketServer
from src.simulator.simulator_constants import test_constants
from setproctitle import setproctitle


async def main():
    """
    Starts WalletNode, WebSocketServer, and ChiaServer
    """
    config = load_config_cli("config.yaml", "wallet")
    initialize_logging("Wallet %(name)-25s", config["logging"])
    log = logging.getLogger(__name__)

    try:
        key_config = load_config("keys.yaml")
    except FileNotFoundError:
        raise RuntimeError(
            "Keys not generated. Run python3 ./scripts/regenerate_keys.py."
        )

    if config["testing"] is True:
        log.info(f"Testing")
        wallet_node = await WalletNode.create(
            config, key_config, override_constants=test_constants
        )
    else:
        log.info(f"Not Testing")
        wallet_node = await WalletNode.create(config, key_config)
    setproctitle("chia_wallet")

    handler = WebSocketServer(wallet_node, log)
    wallet_node.wallet_state_manager.set_callback(handler.state_changed_callback)

    server = ChiaServer(config["port"], wallet_node, NodeType.WALLET)
    wallet_node.set_server(server)

    _ = await server.start_server(config["host"], None, config)
    await asyncio.sleep(1)

    def master_close_cb():
        server.close_all()
        wallet_node._shutdown()

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, master_close_cb)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, master_close_cb)

    await websockets.serve(handler.safe_handle, "localhost", config["rpc_port"])

    wallet_node._start_bg_tasks()

    await server.await_closed()
    await wallet_node.wallet_state_manager.close_all_stores()
    log.info("Wallet fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
