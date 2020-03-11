import asyncio
import dataclasses
import json
import logging

import websockets

from typing import Any, Dict
from aiohttp import web
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

    async def get_next_puzzle_hash(self, websocket, response_api) -> web.Response:
        """
        Returns a new puzzlehash
        """
        puzzlehash = (await self.wallet_node.wallet.get_new_puzzlehash()).hex()

        data = {
            "puzzlehash": puzzlehash,
        }

        await websocket.send(format_response(response_api, data))

    async def send_transaction(self, websocket, request, response_api):
        if "amount" in request and "puzzlehash" in request:
            amount = int(request["amount"])
            puzzlehash = request["puzzlehash"]
            tx = await self.wallet_node.wallet.generate_signed_transaction(
                amount, puzzlehash
            )

            if tx is None:
                data = {"success": False}
                return await websocket.send(format_response(response_api, data))

            await self.wallet_node.wallet.push_transaction(tx)

            data = {"success": True}
            return await websocket.send(format_response(response_api, data))

        data = {"success": False}
        await websocket.send(format_response(response_api, data))

    async def server_ready(self, websocket, response_api):
        response = {"success": True}
        await websocket.send(format_response(response_api, response))

    async def get_transactions(self, websocket, response_api):
        transactions = (
            await self.wallet_node.wallet_state_manager.get_all_transactions()
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

    async def get_wallet_balance(self, websocket, response_api):
        balance = await self.wallet_node.wallet.get_confirmed_balance()
        pending_balance = await self.wallet_node.wallet.get_unconfirmed_balance()

        response = {
            "success": True,
            "confirmed_wallet_balance": balance,
            "unconfirmed_wallet_balance": pending_balance,
        }

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
                await self.server_ready(websocket, command)
            elif command == "get_wallet_balance":
                await self.get_wallet_balance(websocket, command)
            elif command == "send_transaction":
                await self.send_transaction(websocket, data, command)
            elif command == "get_next_puzzle_hash":
                await self.get_next_puzzle_hash(websocket, command)
            elif command == "get_transactions":
                await self.get_transactions(websocket, command)
            elif command == "farm_block":
                await self.farm_block(websocket, data, command)
            else:
                response = {"error": f"unknown_command {command}"}
                await websocket.send(obj_to_response(response))


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
        print("Testing")
        wallet_node = await WalletNode.create(
            config, key_config, override_constants=test_constants
        )
    else:
        print("not testing")
        wallet_node = await WalletNode.create(config, key_config)

    handler = WebSocketServer(wallet_node)
    server = ChiaServer(9257, wallet_node, NodeType.WALLET)
    wallet_node.set_server(server)
    full_node_peer = PeerInfo(
        config["full_node_peer"]["host"], config["full_node_peer"]["port"]
    )

    _ = await server.start_server("127.0.0.1", None)
    await asyncio.sleep(1)
    _ = await server.start_client(full_node_peer, None)

    await websockets.serve(handler.handle_message, "localhost", 9256)

    await server.await_closed()


async def main():
    await start_websocket_server()


if __name__ == "__main__":
    asyncio.run(main())
