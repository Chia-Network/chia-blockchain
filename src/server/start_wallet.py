import asyncio
import signal
import logging

from src.wallet.wallet_node import WalletNode

try:
    import uvloop
except ImportError:
    uvloop = None

from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo
from src.util.logging import initialize_logging
from src.util.config import load_config, load_config_cli
from setproctitle import setproctitle


async def main():
    config = load_config_cli("config.yaml", "wallet")
    try:
        key_config = load_config("keys.yaml")
    except FileNotFoundError:
        raise RuntimeError(
            "Keys not generated. Run python3 ./scripts/regenerate_keys.py."
        )
    initialize_logging("Wallet %(name)-25s", config["logging"])
    log = logging.getLogger(__name__)
    setproctitle("Chia_Wallet")

    wallet = await WalletNode.create(config, key_config)

    full_node_peer = PeerInfo(
        config["full_node_peer"]["host"], config["full_node_peer"]["port"]
    )

    server = ChiaServer(config["port"], wallet, NodeType.WALLET)
    wallet.set_server(server)

    def master_close_cb():
        server.close_all()
        wallet._shutdown()

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, master_close_cb)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, master_close_cb)

    _ = await server.start_server(config["host"], None)
    for i in range(10):
        if await server.start_client(full_node_peer, None):
            break
        await asyncio.sleep(1)

    await server.await_closed()
    await wallet.wallet_state_manager.close_all_stores()
    log.info("Wallet fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
