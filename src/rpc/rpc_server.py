import asyncio
import json
import traceback
from asyncio import create_task
import logging

from typing import Callable, List, Optional, Dict

import aiohttp
from aiohttp import web

from src.full_node.full_node import FullNode
from src.types.header import Header
from src.types.full_block import FullBlock
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32, uint64, uint128
from src.types.sized_bytes import bytes32
from src.util.byte_types import hexstr_to_bytes
from src.util.json_util import obj_to_response
from src.consensus.pot_iterations import calculate_min_iters_from_iterations
from src.util.ws_message import create_payload, format_response, pong
from src.util.logging import initialize_logging

log = logging.getLogger(__name__)


class RpcApiHandler:
    """
    Implementation of full node RPC API.
    Note that this is not the same as the peer protocol, or wallet protocol
    (which run Chia's protocol on top of TCP), it's a separate protocol on top
    of HTTP thats provides easy access to the full node.
    """

    def __init__(self, full_node: FullNode, stop_cb: Callable):
        self.full_node = full_node
        self.stop_cb: Callable = stop_cb
        initialize_logging(
            "RPC FullNode %(name)-25s",
            self.full_node.config["logging"],
            self.full_node.root_path,
        )
        self.log = log
        self.shut_down = False
        self.service_name = "chia_full_node"
        self.cached_blockchain_state = None

    async def stop(self):
        self.shut_down = True
        await self.websocket.close()

    async def _get_blockchain_state(self):
        """
        Returns a summary of the node's view of the blockchain.
        """
        tips: List[Header] = self.full_node.blockchain.get_current_tips()
        lca: Header = self.full_node.blockchain.lca_block
        sync_mode: bool = self.full_node.sync_store.get_sync_mode()
        difficulty: uint64 = self.full_node.blockchain.get_next_difficulty(lca)
        lca_block = await self.full_node.block_store.get_block(lca.header_hash)
        if lca_block is None:
            return None
        min_iters: uint64 = self.full_node.blockchain.get_next_min_iters(lca_block)
        ips: uint64 = min_iters // (
            self.full_node.constants["BLOCK_TIME_TARGET"]
            / self.full_node.constants["MIN_ITERS_PROPORTION"]
        )

        tip_hashes = []
        for tip in tips:
            tip_hashes.append(tip.header_hash)
        if sync_mode and self.full_node.sync_peers_handler is not None:
            sync_tip_height = len(self.full_node.sync_store.get_potential_hashes())
            sync_progress_height = (
                self.full_node.sync_peers_handler.fully_validated_up_to
            )
        else:
            sync_tip_height = 0
            sync_progress_height = uint32(0)

        newer_block_hex = lca.header_hash.hex()
        older_block_hex = self.full_node.blockchain.height_to_hash[max(0, lca.height - 100)].hex()
        space = await self._get_network_space(newer_block_hex, older_block_hex)
        response = {
            "tips": tips,
            "tip_hashes": tip_hashes,
            "lca": lca,
            "sync": {
                "sync_mode": sync_mode,
                "sync_tip_height": sync_tip_height,
                "sync_progress_height": sync_progress_height,
            },
            "difficulty": difficulty,
            "ips": ips,
            "min_iters": min_iters,
            "space": space
        }
        self.cached_blockchain_state = response
        return response

    async def get_blockchain_state(self, request) -> web.Response:
        """
        Returns a summary of the node's view of the blockchain.
        """
        response = await self._get_blockchain_state()
        if response is None:
            raise web.HTTPNotFound()
        return obj_to_response(response)

    async def _get_block(self, header_hash):
        header_hash = hexstr_to_bytes(header_hash)

        block: Optional[FullBlock] = await self.full_node.block_store.get_block(
            header_hash
        )
        return block

    async def get_block(self, request) -> web.Response:
        """
        Retrieves a full block.
        """
        request_data = await request.json()
        if "header_hash" not in request_data:
            raise web.HTTPBadRequest()
        block = await self._get_block(request_data["header_hash"])
        if block is None:
            raise web.HTTPNotFound()
        return obj_to_response(block)

    async def _get_header_by_height(self, height):
        header_height = uint32(int(height))
        header_hash: Optional[bytes32] = self.full_node.blockchain.height_to_hash.get(
            header_height, None
        )
        if header_hash is None:
            return None
        header: Header = self.full_node.blockchain.headers[header_hash]
        return header

    async def get_header_by_height(self, request) -> web.Response:
        """
        Retrieves a header by height.
        """
        request_data = await request.json()
        if "height" not in request_data:
            raise web.HTTPBadRequest()
        header = await self._get_header_by_height(request_data["height"])
        if header is None:
            raise web.HTTPNotFound()
        return obj_to_response(header)

    async def _get_header(self, header_hash_str: str):
        header_hash = hexstr_to_bytes(header_hash_str)
        header: Optional[Header] = self.full_node.blockchain.headers.get(
            header_hash, None
        )
        return header

    async def get_header(self, request) -> web.Response:
        """
        Retrieves a Header.
        """
        request_data = await request.json()
        if "header_hash" not in request_data:
            raise web.HTTPBadRequest()
        header = await self._get_header(request_data["header_hash"])
        if header is None:
            raise web.HTTPNotFound()
        return obj_to_response(header)

    async def _get_unfinished_block_headers(self, height):
        response_headers: List[Header] = []
        for block in (
            await self.full_node.full_node_store.get_unfinished_blocks()
        ).values():
            if block.height == height:
                response_headers.append(block.header)
        return response_headers

    async def _get_latest_block_headers(self):
        headers: Dict[bytes32, Header] = {}
        tips = self.full_node.blockchain.tips
        heights = []
        for tip in tips:
            current = tip
            heights.append(current.height + 1)
            headers[current.header_hash] = current
            for i in range(0, 8):
                if current.height == 0:
                    break
                header: Optional[Header] = self.full_node.blockchain.headers.get(
                    current.prev_header_hash, None
                )
                assert header is not None
                headers[header.header_hash] = header
                current = header

        all_unfinished = {}
        for h in heights:
            unfinished = await self._get_unfinished_block_headers(h)
            for header in unfinished:
                assert header is not None
                all_unfinished[header.header_hash] = header

        sorted_headers = [
            v
            for v in sorted(
                headers.values(), key=lambda item: item.height, reverse=True
            )
        ]
        sorted_unfinished = [
            v
            for v in sorted(
                all_unfinished.values(), key=lambda item: item.height, reverse=True
            )
        ]

        finished_with_meta = []
        finished_header_hashes = set()
        for header in sorted_headers:
            header_hash = header.header_hash
            header_dict = header.to_json_dict()
            header_dict["data"]["header_hash"] = header_hash
            header_dict["data"]["finished"] = True
            finished_with_meta.append(header_dict)
            finished_header_hashes.add(header_hash)

        if self.cached_blockchain_state is None:
            await self._get_blockchain_state()
        assert self.cached_blockchain_state is not None
        ips = self.cached_blockchain_state["ips"]

        unfinished_with_meta = []
        for header in sorted_unfinished:
            header_hash = header.header_hash
            if header_hash in finished_header_hashes:
                continue
            header_dict = header.to_json_dict()
            header_dict["data"]["header_hash"] = header_hash
            header_dict["data"]["finished"] = False
            prev_header = self.full_node.blockchain.headers.get(header.prev_header_hash)
            iter = header.data.total_iters - prev_header.data.total_iters
            time_add = int(iter / ips)
            header_dict["data"]["finish_time"] = header.data.timestamp + time_add
            unfinished_with_meta.append(header_dict)

        unfinished_with_meta.extend(finished_with_meta)

        return unfinished_with_meta

    async def get_total_miniters(self, newer_block, older_block) -> Optional[uint64]:
        """
        Calculates the sum of min_iters from all blocks starting from
        old and up to and including new_block, but not including old_block.
        """
        older_block_parent = await self.full_node.block_store.get_block(
            older_block.prev_header_hash
        )
        if older_block_parent is None:
            return None
        older_diff = older_block.weight - older_block_parent.weight
        curr_mi = calculate_min_iters_from_iterations(
            older_block.proof_of_space,
            older_diff,
            older_block.proof_of_time.number_of_iterations,
        )
        # We do not count the min iters in the old block, since it's not included in the range
        total_mi: uint64 = uint64(0)
        for curr_h in range(older_block.height + 1, newer_block.height + 1):
            if (curr_h % constants["DIFFICULTY_EPOCH"]) == constants["DIFFICULTY_DELAY"]:
                curr_b_header_hash = self.full_node.blockchain.height_to_hash.get(uint32(int(curr_h)))
                if curr_b_header_hash is None:
                    return None
                curr_b_block = await self.full_node.block_store.get_block(curr_b_header_hash)
                if curr_b_block is None or curr_b_block.proof_of_time is None:
                    return None
                curr_parent = await self.full_node.block_store.get_block(
                    curr_b_block.prev_header_hash
                )
                if curr_parent is None:
                    return None
                curr_diff = curr_b_block.weight - curr_parent.weight
                curr_mi = calculate_min_iters_from_iterations(
                    curr_b_block.proof_of_space,
                    uint64(curr_diff),
                    curr_b_block.proof_of_time.number_of_iterations,
                )
                if curr_mi is None:
                    raise web.HTTPBadRequest()
            total_mi = uint64(total_mi + curr_mi)

        # print("Minimum iterations:", total_mi)
        return total_mi

    async def _get_network_space(self, newer_block_hex, older_block_hex) -> uint128:
        newer_block_bytes = hexstr_to_bytes(newer_block_hex)
        older_block_bytes = hexstr_to_bytes(older_block_hex)

        newer_block = await self.full_node.block_store.get_block(newer_block_bytes)
        if newer_block is None:
            raise web.HTTPNotFound()
        older_block = await self.full_node.block_store.get_block(older_block_bytes)
        if older_block is None:
            raise web.HTTPNotFound()
        delta_weight = newer_block.header.data.weight - older_block.header.data.weight
        delta_iters = (
            newer_block.header.data.total_iters - older_block.header.data.total_iters
        )
        total_min_inters = await self.get_total_miniters(newer_block, older_block)
        if total_min_inters is None:
            raise web.HTTPNotFound()
        delta_iters -= total_min_inters
        weight_div_iters = delta_weight / delta_iters
        tips_adjustment_constant = 0.65
        network_space_constant = 2 ** 32  # 2^32
        network_space_bytes_estimate = (
            weight_div_iters * network_space_constant * tips_adjustment_constant
        )
        return uint128(int(network_space_bytes_estimate))


    async def get_network_space(self, request) -> web.Response:
        """
        Retrieves an estimate of total space validating the chain
        between two block header hashes.
        """
        request_data = await request.json()
        if (
            "newer_block_header_hash" not in request_data
            or "older_block_header_hash" not in request_data
        ):
            raise web.HTTPBadRequest()
        newer_block_hex = request_data["newer_block_header_hash"]
        older_block_hex = request_data["older_block_header_hash"]

        return obj_to_response(await self._get_network_space(newer_block_hex, older_block_hex))

    async def get_unfinished_block_headers(self, request) -> web.Response:
        request_data = await request.json()
        if "height" not in request_data:
            raise web.HTTPBadRequest()
        height = request_data["height"]
        response_headers = await self._get_unfinished_block_headers(height)
        return obj_to_response(response_headers)

    async def _get_connections(self):
        if self.full_node.server is None:
            return []
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
        return con_info

    async def get_connections(self, request) -> web.Response:
        """
        Retrieves all connections to this full node, including farmers and timelords.
        """
        con_info = await self._get_connections()
        return obj_to_response(con_info)

    async def _open_connection(self, host, port):
        target_node: PeerInfo = PeerInfo(host, uint16(int(port)))

        if self.full_node.server is None or not (
            await self.full_node.server.start_client(target_node, None)
        ):
            raise web.HTTPInternalServerError()

    async def open_connection(self, request) -> web.Response:
        """
        Opens a new connection to another node.
        """
        request_data = await request.json()
        host = request_data["host"]
        port = request_data["port"]
        await self._open_connection(host, port)
        return obj_to_response("")

    def _close_connection(self, node_id):
        node_id = hexstr_to_bytes(node_id)
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

    async def close_connection(self, request) -> web.Response:
        """
        Closes a connection given by the node id.
        """
        request_data = await request.json()
        self._close_connection(request_data["node_id"])
        return obj_to_response("")

    def _stop_node(self):
        if self.stop_cb is not None:
            self.stop_cb()

    async def stop_node(self, request) -> web.Response:
        """
        Shuts down the node.
        """
        self._stop_node()
        return obj_to_response("")

    async def _get_unspent_coins(self, puzzle_hash, header_hash=None):
        if header_hash is not None:
            header_hash = bytes32(hexstr_to_bytes(header_hash))
            header = self.full_node.blockchain.headers.get(header_hash)
        else:
            header = None

        coin_records = await self.full_node.blockchain.coin_store.get_coin_records_by_puzzle_hash(
            puzzle_hash, header
        )

        return coin_records

    async def get_unspent_coins(self, request) -> web.Response:
        """
        Retrieves the unspent coins for a given puzzlehash.
        """
        request_data = await request.json()
        puzzle_hash = hexstr_to_bytes(request_data["puzzle_hash"])
        if "header_hash" in request_data:
            result = await self._get_unspent_coins(
                puzzle_hash, request_data["header_hash"]
            )
        else:
            result = await self._get_unspent_coins(puzzle_hash)

        return obj_to_response(result)

    async def _get_heaviest_block_seen(self):
        tips: List[Header] = self.full_node.blockchain.get_current_tips()
        tip_weights = [tip.weight for tip in tips]
        i = tip_weights.index(max(tip_weights))
        max_tip: Header = tips[i]
        if self.full_node.sync_store.get_sync_mode():
            potential_tips = self.full_node.sync_store.get_potential_tips_tuples()
            for _, pot_block in potential_tips:
                if pot_block.weight > max_tip.weight:
                    max_tip = pot_block.header

    async def get_heaviest_block_seen(self, request) -> web.Response:
        """
        Returns the heaviest block ever seen, whether it's been added to the blockchain or not
        """
        max_tip = await self._get_heaviest_block_seen()
        return obj_to_response(max_tip)

    async def ws_api(self, message):
        """
        This function gets called when new message is received via websocket.
        """

        command = message["command"]
        if message["ack"]:
            return None

        data = None
        if "data" in message:
            data = message["data"]
        if command == "ping":
            return pong()
        elif command == "get_heaviest_block":
            response = await self._get_heaviest_block_seen()
            return response
        elif command == "get_unspent_coins":
            assert data is not None
            puzzle_hash = data["puzzle_hash"]
            header_hash = None
            if "header_hash" in data:
                header_hash = data["header_hash"]
            return await self._get_unspent_coins(puzzle_hash, header_hash)
        elif command == "stop_node":
            await self._stop_node()
            response = {"success": True}
            return response
        elif command == "close_connection":
            assert data is not None
            node_id = data["node_id"]
            return await self._close_connection(node_id)
        elif command == "get_blockchain_state":
            return await self._get_blockchain_state()
        elif command == "get_latest_block_headers":
            headers = await self._get_latest_block_headers()
            response = {"success": True, "headers": headers}
            return response
        else:
            response = {"error": f"unknown_command {command}"}
            return response

    async def safe_handle(self, websocket, payload):
        message = None
        try:
            message = json.loads(payload)
            response = await self.ws_api(message)
            if response is not None:
                # self.log.info(f"message: {message}")
                # self.log.info(f"response: {response}")
                # self.log.info(f"payload: {format_response(message, response)}")
                await websocket.send_str(format_response(message, response))

        except BaseException as e:
            tb = traceback.format_exc()
            self.log.error(f"Error while handling message: {tb}")
            error = {"success": False, "error": f"{e}"}
            if message is None:
                return
            await websocket.send_str(format_response(message, error))

    async def connection(self, ws):
        data = {"service": self.service_name}
        payload = create_payload("register_service", data, self.service_name, "daemon")
        await ws.send_str(payload)

        while True:
            msg = await ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                message = msg.data.strip()
                self.log.info(f"received message: {message}")
                await self.safe_handle(ws, message)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                self.log.warning("Received binary data")
            elif msg.type == aiohttp.WSMsgType.PING:
                await ws.pong()
            elif msg.type == aiohttp.WSMsgType.PONG:
                self.log.info("Pong received")
            else:
                if msg.type == aiohttp.WSMsgType.CLOSE:
                    self.log.info("Closing")
                    await ws.close()
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.log.info("Error during receive %s" % ws.exception())
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    pass

                break

        await ws.close()

    async def connect_to_daemon(self):
        while True:
            session = None
            try:
                if self.shut_down:
                    break
                session = aiohttp.ClientSession()
                async with session.ws_connect(
                    "ws://127.0.0.1:55400", autoclose=False, autoping=True
                ) as ws:
                    self.websocket = ws
                    await self.connection(ws)
                self.websocket = None
                await session.close()
            except BaseException as e:
                self.log.error(f"Exception: {e}")
                if session is not None:
                    await session.close()
                pass
            await asyncio.sleep(1)


async def start_rpc_server(
    full_node: FullNode, stop_node_cb: Callable, rpc_port: uint16
):
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
            web.post("/get_header_by_height", handler.get_header_by_height),
            web.post("/get_header", handler.get_header),
            web.post(
                "/get_unfinished_block_headers", handler.get_unfinished_block_headers
            ),
            web.post("/get_network_space", handler.get_network_space),
            web.post("/get_connections", handler.get_connections),
            web.post("/open_connection", handler.open_connection),
            web.post("/close_connection", handler.close_connection),
            web.post("/stop_node", handler.stop_node),
            web.post("/get_unspent_coins", handler.get_unspent_coins),
            web.post("/get_heaviest_block_seen", handler.get_heaviest_block_seen),
        ]
    )

    daemon_connection = create_task(handler.connect_to_daemon())
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", int(rpc_port))
    await site.start()

    async def cleanup():
        await handler.stop()
        await runner.cleanup()
        await daemon_connection

    return cleanup
