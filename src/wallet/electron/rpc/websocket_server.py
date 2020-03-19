import asyncio
import dataclasses
import json
import logging

import websockets

from typing import Any, Dict
from src.server.outbound_message import NodeType, OutboundMessage, Message, Delivery
from src.server.server import ChiaServer
from src.simulator.simulator_constants import test_constants
from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.types.peer_info import PeerInfo
from src.util.config import load_config, load_config_cli
from src.util.logging import initialize_logging
from src.wallet.wallet_node import WalletNode


class EnhancedJSONEncoder(json.JSONEncoder):
    """
    Encodes bytes as hex strings with 0x, and converts all dataclasses to json.
    """

    def default(self, o: Any):
        if dataclasses.is_dataclass(o):
            return o.to_json()
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
    def __init__(self, wallet_node: WalletNode):
        self.wallet_node: WalletNode = wallet_node
        self.websocket = None

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

        tx = await wallet.generate_signed_transaction_dict(
            request
        )

        if tx is None:
            data = {"success": False}
            return await websocket.send(format_response(response_api, data))

        await wallet.push_transaction(tx)

        data = {"success": True}
        return await websocket.send(format_response(response_api, data))

    async def server_ready(self, websocket, response_api):
        response = {"success": True}
        await websocket.send(format_response(response_api, response))

    async def get_transactions(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        transactions = (
            await self.wallet_node.wallet_state_manager.get_all_transactions(wallet_id)
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
            else:
                response = {"error": f"unknown_command {command}"}
                await websocket.send(obj_to_response(response))

    async def notify_ui_that_state_changed(self, state: str):
        data = {
            "state": state,
        }

        await self.websocket.send(format_response("state_changed", data))

    def state_changed_callback(self, state: str):
        if self.websocket is None:
            return
        asyncio.ensure_future(self.notify_ui_that_state_changed(state))


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

    handler = WebSocketServer(wallet_node)
    wallet_node.wallet_state_manager.set_callback(handler.state_changed_callback)

    server = ChiaServer(9257, wallet_node, NodeType.WALLET)
    wallet_node.set_server(server)
    full_node_peer = PeerInfo(
        config["full_node_peer"]["host"], config["full_node_peer"]["port"]
    )

    _ = await server.start_server("127.0.0.1", None, config)
    await asyncio.sleep(1)
    _ = await server.start_client(full_node_peer, None, config)

    await websockets.serve(handler.handle_message, "localhost", 9256)

    if config["testing"] is False:
        wallet_node._start_bg_tasks()

    await server.await_closed()


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_websocket_server())


if __name__ == "__main__":
    main()
