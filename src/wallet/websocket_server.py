import asyncio
import logging
import signal
from pathlib import Path

from typing import Optional


try:
    import uvloop
except ImportError:
    uvloop = None

from src.server.server import ChiaServer
from src.util.config import load_config_cli, load_config
from src.wallet.wallet_node import WalletNode
from src.util.logging import initialize_logging
from src.util.keychain import Keychain
from src.wallet.trade_manager import TradeManager
from src.server.connection import NodeType
from src.simulator.simulator_constants import test_constants


# Timeout for response from wallet/full node for sending a transaction
TIMEOUT = 30

log = logging.getLogger(__name__)


class WebSocketServer:
    def __init__(self, keychain: Keychain, root_path: Path):
        self.config = load_config_cli(root_path, "config.yaml", "wallet")
        initialize_logging("Wallet %(name)-25s", self.config["logging"], root_path)
        self.log = log
        self.keychain = keychain
        self.websocket = None
        self.root_path = root_path
        self.wallet_node: Optional[WalletNode] = None
        self.trade_manager: Optional[TradeManager] = None
        self.shut_down = False
        if self.config["testing"] is True:
            self.config["database_path"] = "test_db_wallet.db"

    async def start(self):
        self.log.info("Starting Websocket Server")

        def master_close_cb():
            asyncio.ensure_future(self.stop())

        try:
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGINT, master_close_cb
            )
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGTERM, master_close_cb
            )
        except NotImplementedError:
            self.log.info("Not implemented")

        await self.start_wallet()

        await self.connect_to_daemon()
        self.log.info("webSocketServer closed")

    async def start_wallet(self, public_key_fingerprint: Optional[int] = None) -> bool:
        private_keys = self.keychain.get_all_private_keys()
        if len(private_keys) == 0:
            self.log.info("No keys")
            return False

        if public_key_fingerprint is not None:
            for sk, _ in private_keys:
                if sk.get_public_key().get_fingerprint() == public_key_fingerprint:
                    private_key = sk
                    break
        else:
            private_key = private_keys[0][0]

        if private_key is None:
            self.log.info("No keys")
            return False

        if self.config["testing"] is True:
            log.info("Websocket server in testing mode")
            self.wallet_node = await WalletNode.create(
                self.config,
                private_key,
                self.root_path,
                override_constants=test_constants,
                local_test=True,
            )
        else:
            self.wallet_node = await WalletNode.create(
                self.config, private_key, self.root_path
            )

        if self.wallet_node is None:
            return False

        self.trade_manager = await TradeManager.create(
            self.wallet_node.wallet_state_manager
        )
        self.wallet_node.wallet_state_manager.set_callback(self.state_changed_callback)

        net_config = load_config(self.root_path, "config.yaml")
        ping_interval = net_config.get("ping_interval")
        network_id = net_config.get("network_id")
        assert ping_interval is not None
        assert network_id is not None

        server = ChiaServer(
            self.config["port"],
            self.wallet_node,
            NodeType.WALLET,
            ping_interval,
            network_id,
            self.root_path,
            self.config,
        )
        self.wallet_node.set_server(server)

        self.wallet_node._start_bg_tasks()

        return True

    async def stop(self):
        self.shut_down = True
        if self.wallet_node is not None:
            self.wallet_node.server.close_all()
            self.wallet_node._shutdown()
            await self.wallet_node.wallet_state_manager.close_all_stores()
        self.log.info("closing websocket")
        if self.websocket is not None:
            self.log.info("closing websocket 2")
            await self.websocket.close()
        self.log.info("closied websocket")

    def state_changed_callback(self, state: str, wallet_id: int = None):
        if self.websocket is None:
            return
        asyncio.create_task(self.notify_ui_that_state_changed(state, wallet_id))
