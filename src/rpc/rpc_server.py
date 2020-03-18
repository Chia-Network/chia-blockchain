import dataclasses
import json

from typing import Any, Callable, List, Optional

from aiohttp import web

from src.full_node.full_node import FullNode
from src.types.header import Header
from src.types.full_block import FullBlock
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint64
from src.types.sized_bytes import bytes32
from src.util.byte_types import hexstr_to_bytes
from src.util.config import load_config


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


class RpcApiHandler:
    """
    Implementation of full node RPC API.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP thats provides easy access
    to the full node.
    """

    def __init__(self, full_node: FullNode, stop_cb: Callable):
        self.full_node = full_node
        self.stop_cb: Callable = stop_cb

    async def get_blockchain_state(self, request) -> web.Response:
        """
        Returns a summary of the node's view of the blockchain.
        """
        tips: List[Header] = self.full_node.blockchain.get_current_tips()
        lca: Header = self.full_node.blockchain.lca_block
        sync_mode: bool = self.full_node.store.get_sync_mode()
        difficulty: uint64 = self.full_node.blockchain.get_next_difficulty(
            lca.header_hash
        )
        lca_block = await self.full_node.store.get_block(lca.header_hash)
        if lca_block is None:
            raise web.HTTPNotFound()
        min_iters: uint64 = self.full_node.blockchain.get_next_min_iters(lca_block)
        ips: uint64 = min_iters // (
            self.full_node.constants["BLOCK_TIME_TARGET"]
            / self.full_node.constants["MIN_ITERS_PROPORTION"]
        )
        response = {
            "tips": tips,
            "lca": lca,
            "sync_mode": sync_mode,
            "difficulty": difficulty,
            "ips": ips,
            "min_iters": min_iters,
        }
        return obj_to_response(response)

    async def get_block(self, request) -> web.Response:
        """
        Retrieves a full block.
        """
        request_data = await request.json()
        if "header_hash" not in request_data:
            raise web.HTTPBadRequest()
        header_hash = hexstr_to_bytes(request_data["header_hash"])

        block: Optional[FullBlock] = await self.full_node.store.get_block(header_hash)
        if block is None:
            raise web.HTTPNotFound()
        return obj_to_response(block)

    async def get_header(self, request) -> web.Response:
        """
        Retrieves a Header.
        """
        request_data = await request.json()
        if "header_hash" not in request_data:
            raise web.HTTPBadRequest()
        header_hash = hexstr_to_bytes(request_data["header_hash"])
        header: Optional[Header] = self.full_node.blockchain.headers.get(
            header_hash, None
        )
        if header is None:
            raise web.HTTPNotFound()
        return obj_to_response(header)

    async def get_connections(self, request) -> web.Response:
        """
        Retrieves all connections to this full node, including farmers and timelords.
        """
        if self.full_node.server is None:
            return obj_to_response([])
        connections = self.full_node.server.global_connections.get_connections()
        con_info = [
            {
                "type": con.connection_type,
                "local_host": con.local_host,
                "local_port": con.local_port,
                "peer_host": con.peer_host,
                "peer_port": con.peer_port,
                "peer_server_port": con.peer_server_port,
                "node_id": con.node_id,
                "creation_time": con.creation_time,
                "bytes_read": con.bytes_read,
                "bytes_written": con.bytes_written,
                "last_message_time": con.last_message_time,
            }
            for con in connections
        ]
        return obj_to_response(con_info)

    async def open_connection(self, request) -> web.Response:
        """
        Opens a new connection to another node.
        """
        request_data = await request.json()
        host = request_data["host"]
        port = request_data["port"]
        target_node: PeerInfo = PeerInfo(host, uint16(int(port)))

        config = load_config("config.yaml", "full_node")
        if self.full_node.server is None or not (
            await self.full_node.server.start_client(target_node, None, config)
        ):
            raise web.HTTPInternalServerError()
        return obj_to_response("")

    async def close_connection(self, request) -> web.Response:
        """
        Closes a connection given by the node id.
        """
        request_data = await request.json()
        node_id = hexstr_to_bytes(request_data["node_id"])
        if self.full_node.server is None:
            raise web.HTTPInternalServerError()

        connections_to_close = [
            c
            for c in self.full_node.server.global_connections.get_connections()
            if c.node_id == node_id
        ]
        if len(connections_to_close) == 0:
            raise web.HTTPNotFound()
        for connection in connections_to_close:
            self.full_node.server.global_connections.close(connection)
        return obj_to_response("")

    async def stop_node(self, request) -> web.Response:
        """
        Shuts down the node.
        """
        if self.stop_cb is not None:
            self.stop_cb()
        return obj_to_response("")

    async def get_unspent_coins(self, request) -> web.Response:
        """
        Retrieves the unspent coins for a given puzzlehash.
        """
        request_data = await request.json()
        puzzle_hash = hexstr_to_bytes(request_data["puzzle_hash"])
        if "header_hash" in request_data:
            header_hash = bytes32(hexstr_to_bytes(request_data["header_hash"]))
            header = self.full_node.blockchain.headers.get(header_hash)
        else:
            header = None

        coin_records = await self.full_node.blockchain.unspent_store.get_coin_records_by_puzzle_hash(
            puzzle_hash, header
        )

        return obj_to_response(coin_records)

    async def get_heaviest_block_seen(self, request) -> web.Response:
        """
        Returns the heaviest block ever seen, whether it's been added to the blockchain or not
        """
        tips: List[Header] = self.full_node.blockchain.get_current_tips()
        tip_weights = [tip.weight for tip in tips]
        i = tip_weights.index(max(tip_weights))
        max_tip: Header = tips[i]
        if self.full_node.store.get_sync_mode():
            potential_tips = self.full_node.store.get_potential_tips_tuples()
            for _, pot_block in potential_tips:
                if pot_block.weight > max_tip.weight:
                    max_tip = pot_block.header
        return obj_to_response(max_tip)


async def start_rpc_server(full_node: FullNode, stop_node_cb: Callable, rpc_port: int):
    """
    Starts an HTTP server with the following RPC methods, to be used by local clients to
    query the node.
    """
    handler = RpcApiHandler(full_node, stop_node_cb)
    app = web.Application()
    app.add_routes(
        [
            web.post("/get_blockchain_state", handler.get_blockchain_state),
            web.post("/get_block", handler.get_block),
            web.post("/get_header", handler.get_header),
            web.post("/get_connections", handler.get_connections),
            web.post("/open_connection", handler.open_connection),
            web.post("/close_connection", handler.close_connection),
            web.post("/stop_node", handler.stop_node),
            web.post("/get_unspent_coins", handler.get_unspent_coins),
            web.post("/get_heaviest_block_seen", handler.get_heaviest_block_seen),
        ]
    )
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", rpc_port)
    await site.start()

    async def cleanup():
        await runner.cleanup()

    return cleanup
