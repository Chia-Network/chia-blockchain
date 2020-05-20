import asyncio
import logging
import traceback

from src.util.keychain import Keychain

try:
    import uvloop
except ImportError:
    uvloop = None

from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.setproctitle import setproctitle
from src.wallet.websocket_server import WebSocketServer


log = logging.getLogger(__name__)


async def start_websocket_server():
    """
    Starts WalletNode, WebSocketServer, and ChiaServer
    """

    setproctitle("chia-wallet")
    keychain = Keychain(testing=False)
    websocket_server = WebSocketServer(keychain, DEFAULT_ROOT_PATH)
    await websocket_server.start()
    log.info("Wallet fully closed")


def main():
    if uvloop is not None:
        uvloop.install()
    asyncio.run(start_websocket_server())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        log.error(f"Error in wallet. {tb}")
        raise
