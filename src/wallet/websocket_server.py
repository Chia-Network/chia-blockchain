import asyncio
import dataclasses
import json
import logging
import signal
import time
import traceback

from typing import Any, Dict, List, Optional, Tuple

import websockets

from src.types.peer_info import PeerInfo

try:
    import uvloop
except ImportError:
    uvloop = None

from src.server.outbound_message import NodeType, OutboundMessage, Message, Delivery
from src.server.server import ChiaServer
from src.simulator.simulator_constants import test_constants
from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.util.config import load_config_cli, load_config
from src.util.ints import uint64
from src.util.logging import initialize_logging
from src.wallet.rl_wallet.rl_wallet import RLWallet
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet_info import WalletInfo
from src.wallet.wallet_node import WalletNode
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from setproctitle import setproctitle

# Timeout for response from wallet/full node for sending a transaction
TIMEOUT = 5


class EnhancedJSONEncoder(json.JSONEncoder):
    """
    Encodes bytes as hex strings with 0x, and converts all dataclasses to json.
    """

    def default(self, o: Any):
        if dataclasses.is_dataclass(o):
            return o.to_json_dict()
        elif isinstance(o, WalletType):
            return o.name
        elif hasattr(type(o), "__bytes__"):
            return f"0x{bytes(o).hex()}"
        return super().default(o)


def obj_to_response(o: Any) -> str:
    """
    Converts a python object into json.
    """
    json_str = json.dumps(o, cls=EnhancedJSONEncoder, sort_keys=True)
    return json_str


def format_response(command: str, response_data: Dict[str, Any]):
    """
    Formats the response into standard format used between renderer.js and here
    """
    response = {"command": command, "data": response_data}

    json_str = obj_to_response(response)
    return json_str


class WebSocketServer:
    def __init__(self, wallet_node: WalletNode, log):
        self.wallet_node: WalletNode = wallet_node
        self.websocket = None
        self.log = log

    async def get_next_puzzle_hash(self, websocket, request, response_api):
        """
        Returns a new puzzlehash
        """

        wallet_id = int(request["wallet_id"])
        wallet = self.wallet_node.wallets[wallet_id]
        puzzlehash = (await wallet.get_new_puzzlehash()).hex()

        data = {
            "puzzlehash": puzzlehash,
        }

        await websocket.send(format_response(response_api, data))

    async def send_transaction(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet = self.wallet_node.wallets[wallet_id]
        try:
            tx = await wallet.generate_signed_transaction_dict(request)
        except BaseException as e:
            data = {
                "status": "FAILED",
                "reason": f"Failed to generate signed transaction {e}",
            }
            return await websocket.send(format_response(response_api, data))

        if tx is None:
            data = {
                "status": "FAILED",
                "reason": "Failed to generate signed transaction",
            }
            return await websocket.send(format_response(response_api, data))
        try:
            await wallet.push_transaction(tx)
        except BaseException as e:
            data = {
                "status": "FAILED",
                "reason": f"Failed to push transaction {e}",
            }
            return await websocket.send(format_response(response_api, data))
        self.log.error(tx)
        sent = False
        start = time.time()
        while time.time() - start < TIMEOUT:
            sent_to: List[
                Tuple[str, MempoolInclusionStatus, Optional[str]]
            ] = await wallet.get_transaction_status(tx.name())

            if len(sent_to) == 0:
                await asyncio.sleep(0.1)
                continue
            status, err = sent_to[0][1], sent_to[0][2]
            if status == MempoolInclusionStatus.SUCCESS:
                data = {"status": "SUCCESS"}
                sent = True
                break
            elif status == MempoolInclusionStatus.PENDING:
                assert err is not None
                data = {"status": "PENDING", "reason": err}
                sent = True
                break
            elif status == MempoolInclusionStatus.FAILED:
                assert err is not None
                data = {"status": "FAILED", "reason": err}
                sent = True
                break
        if not sent:
            data = {
                "status": "FAILED",
                "reason": "Timed out. Transaction may or may not have been sent.",
            }

        return await websocket.send(format_response(response_api, data))

    async def server_ready(self, websocket, response_api):
        response = {"success": True}
        await websocket.send(format_response(response_api, response))

    async def get_transactions(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        transactions = await self.wallet_node.wallet_state_manager.get_all_transactions(
            wallet_id
        )

        response = {"success": True, "txs": transactions}
        await websocket.send(format_response(response_api, response))

    async def farm_block(self, websocket, request, response_api):
        puzzle_hash = bytes.fromhex(request["puzzle_hash"])
        request = FarmNewBlockProtocol(puzzle_hash)
        msg = OutboundMessage(
            NodeType.FULL_NODE, Message("farm_new_block", request), Delivery.BROADCAST,
        )

        self.wallet_node.server.push_message(msg)

    async def get_wallet_balance(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet = self.wallet_node.wallets[wallet_id]
        balance = await wallet.get_confirmed_balance()
        pending_balance = await wallet.get_unconfirmed_balance()

        response = {
            "wallet_id": wallet_id,
            "success": True,
            "confirmed_wallet_balance": balance,
            "unconfirmed_wallet_balance": pending_balance,
        }

        await websocket.send(format_response(response_api, response))

    async def get_sync_status(self, websocket, response_api):
        syncing = self.wallet_node.wallet_state_manager.sync_mode

        response = {"syncing": syncing}

        await websocket.send(format_response(response_api, response))

    async def get_height_info(self, websocket, response_api):
        lca = self.wallet_node.wallet_state_manager.lca
        height = self.wallet_node.wallet_state_manager.block_records[lca].height

        response = {"height": height}

        await websocket.send(format_response(response_api, response))

    async def get_connection_info(self, websocket, response_api):
        connections = (
            self.wallet_node.server.global_connections.get_full_node_peerinfos()
        )

        response = {"connections": connections}

        await websocket.send(format_response(response_api, response))

    async def create_new_wallet(self, websocket, request, response_api):
        config, key_config, wallet_state_manager, main_wallet = self.get_wallet_config()
        if request["wallet_type"] == "rl_wallet":
            if request["mode"] == "admin":
                rl_admin: RLWallet = await RLWallet.create_rl_admin(
                    config, key_config, wallet_state_manager, main_wallet
                )
                self.wallet_node.wallets[rl_admin.wallet_info.id] = rl_admin
                response = {"success": True, "type": "rl_wallet"}
                return await websocket.send(format_response(response_api, response))
            elif request["mode"] == "user":
                rl_user: RLWallet = await RLWallet.create_rl_user(
                    config, key_config, wallet_state_manager, main_wallet
                )
                self.wallet_node.wallets[rl_user.wallet_info.id] = rl_user
                response = {"success": True, "type": "rl_wallet"}
                return await websocket.send(format_response(response_api, response))
        elif request["wallet_type"] == "cc_wallet":
            print("Create me!!")

        response = {"success": False}
        return await websocket.send(format_response(response_api, response))

    def get_wallet_config(self):
        return (
            self.wallet_node.config,
            self.wallet_node.key_config,
            self.wallet_node.wallet_state_manager,
            self.wallet_node.main_wallet,
        )

    async def get_wallets(self, websocket, response_api):
        wallets: List[
            WalletInfo
        ] = await self.wallet_node.wallet_state_manager.get_all_wallets()

        response = {"wallets": wallets}

        return await websocket.send(format_response(response_api, response))

    async def rl_set_admin_info(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet: RLWallet = self.wallet_node.wallets[wallet_id]
        user_pubkey = request["user_pubkey"]
        limit = uint64(int(request["limit"]))
        interval = uint64(int(request["interval"]))
        amount = uint64(int(request["amount"]))

        success = await wallet.admin_create_coin(interval, limit, user_pubkey, amount)

        response = {"success": success}

        return await websocket.send(format_response(response_api, response))

    async def rl_set_user_info(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet: RLWallet = self.wallet_node.wallets[wallet_id]
        admin_pubkey = request["admin_pubkey"]
        limit = uint64(int(request["limit"]))
        interval = uint64(int(request["interval"]))
        origin_id = request["origin_id"]

        success = await wallet.set_user_info(interval, limit, origin_id, admin_pubkey)

        response = {"success": success}

        return await websocket.send(format_response(response_api, response))

    async def safe_handle(self, websocket, path):
        try:
            await self.handle_message(websocket, path)
        except (BaseException, websockets.exceptions.ConnectionClosedError) as e:
            if isinstance(e, websockets.exceptions.ConnectionClosedError):
                self.log.warning("ConnectionClosedError. Closing websocket.")
                await websocket.close()
            else:
                tb = traceback.format_exc()
                self.log.error(f"Error while handling message: {tb}")

    async def handle_message(self, websocket, path):
        """
        This function gets called when new message is received via websocket.
        """

        async for message in websocket:
            decoded = json.loads(message)
            command = decoded["command"]
            data = None
            if "data" in decoded:
                data = decoded["data"]
            if command == "start_server":
                self.websocket = websocket
                await self.server_ready(websocket, command)
            elif command == "get_wallet_balance":
                await self.get_wallet_balance(websocket, data, command)
            elif command == "send_transaction":
                await self.send_transaction(websocket, data, command)
            elif command == "get_next_puzzle_hash":
                await self.get_next_puzzle_hash(websocket, data, command)
            elif command == "get_transactions":
                await self.get_transactions(websocket, data, command)
            elif command == "farm_block":
                await self.farm_block(websocket, data, command)
            elif command == "get_sync_status":
                await self.get_sync_status(websocket, command)
            elif command == "get_height_info":
                await self.get_height_info(websocket, command)
            elif command == "get_connection_info":
                await self.get_connection_info(websocket, command)
            elif command == "create_new_wallet":
                await self.create_new_wallet(websocket, data, command)
            elif command == "get_wallets":
                await self.get_wallets(websocket, command)
            elif command == "rl_set_admin_info":
                await self.rl_set_admin_info(websocket, data, command)
            elif command == "rl_set_user_info":
                await self.rl_set_user_info(websocket, data, command)
            else:
                response = {"error": f"unknown_command {command}"}
                await websocket.send(obj_to_response(response))

    async def notify_ui_that_state_changed(self, state: str):
        data = {
            "state": state,
        }
        if self.websocket is not None:
            # try:
            await self.websocket.send(format_response("state_changed", data))
            # except Conne

    def state_changed_callback(self, state: str):
        if self.websocket is None:
            return
        asyncio.create_task(self.notify_ui_that_state_changed(state))


async def start_websocket_server():
    """
    Starts WalletNode, WebSocketServer, and ChiaServer
    """

    config = load_config_cli("config.yaml", "wallet")
    initialize_logging("Wallet %(name)-25s", config["logging"])
    log = logging.getLogger(__name__)
    log.info(f"Config : {config}")

    try:
        key_config = load_config("keys.yaml")
    except FileNotFoundError:
        raise RuntimeError(
            "Keys not generated. Run python3 ./scripts/generate_keys.py."
        )
    if config["testing"] is True:
        log.info(f"Testing")
        config["database_path"] = "test_db_wallet.db"
        wallet_node = await WalletNode.create(
            config, key_config, override_constants=test_constants
        )
    else:
        log.info(f"Not Testing")
        wallet_node = await WalletNode.create(config, key_config)
    setproctitle("chia-wallet")
    handler = WebSocketServer(wallet_node, log)
    wallet_node.wallet_state_manager.set_callback(handler.state_changed_callback)

    log.info(f"Starting wallet server on port {config['port']}.")
    server = ChiaServer(config["port"], wallet_node, NodeType.WALLET)
    wallet_node.set_server(server)

    _ = await server.start_server("127.0.0.1", None, config)
    full_node_peer = PeerInfo(
        config["full_node_peer"]["host"], config["full_node_peer"]["port"]
    )

    log.info(f"Connecting to full node peer at {full_node_peer}")
    server.global_connections.peers.add(full_node_peer)
    _ = await server.start_client(full_node_peer, None, config)

    log.info("Starting websocket server.")
    websocket_server = await websockets.serve(
        handler.safe_handle, "localhost", config["rpc_port"]
    )
    log.info(f"Started websocket server at port {config['rpc_port']}.")

    def master_close_cb():
        server.close_all()
        websocket_server.close()
        wallet_node._shutdown()

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, master_close_cb)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, master_close_cb)

    if config["testing"] is False:
        wallet_node._start_bg_tasks()

    await server.await_closed()
    await websocket_server.wait_closed()
    await wallet_node.wallet_state_manager.close_all_stores()
    log.info("Wallet fully closed")


def main():
    if uvloop is not None:
        uvloop.install()
    asyncio.run(start_websocket_server())


if __name__ == "__main__":
    main()
