import asyncio
import dataclasses
import json

from typing import Any

from aiohttp import web
from blspy import ExtendedPrivateKey

from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.wallet.wallet import Wallet


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


def obj_to_response(o: Any) -> web.Response:
    """
    Converts a python object into json.
    """
    json_str = json.dumps(o, cls=EnhancedJSONEncoder, sort_keys=True)
    return web.Response(body=json_str, content_type="application/json")


class RpcWalletApiHandler:
    """
    Implementation of full node RPC API.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP thats provides easy access
    to the full node.
    """

    def __init__(self, wallet: Wallet):
        self.wallet = wallet

    async def get_next_puzzle_hash(self, request) -> web.Response:
        """
        Returns a new puzzlehash
        """
        print("hello1")
        puzzlehash = self.wallet.get_new_puzzlehash().hex()
        response = {
            "puzzlehash": puzzlehash,
        }
        return obj_to_response(response)


async def start_rpc_server():
    """
    Starts an HTTP server with the following RPC methods, to be used by local clients to
    query the node.
    """
    sk = bytes(ExtendedPrivateKey.from_seed(b"")).hex()
    key_config = {"wallet_sk": sk}

    wallet = await Wallet.create({}, key_config)
    server = ChiaServer(9257, wallet, NodeType.WALLET)
    wallet.set_server(server)
    _ = await server.start_server("127.0.0.1", wallet._on_connect)

    handler = RpcWalletApiHandler(wallet)
    app = web.Application()
    app.add_routes(
        [
            web.post("/get_next_puzzle_hash", handler.get_next_puzzle_hash),
        ]
    )
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", 9256)
    await site.start()
    await server.await_closed()

    async def cleanup():
        await runner.cleanup()

    return cleanup


async def main():
    cleanup = await start_rpc_server()
    print('start running on {}')
    await cleanup()

if __name__ == '__main__':
    asyncio.run(main())
