from src.full_node.full_node import FullNode
from src.util.ints import uint16
from src.rpc.abstract_rpc_server import AbstractRpcApiHandler, start_rpc_server
from typing import Callable, List, Optional, Dict

from aiohttp import web

from src.types.header import Header
from src.types.full_block import FullBlock
from src.util.ints import uint32, uint64, uint128
from src.types.sized_bytes import bytes32
from src.util.byte_types import hexstr_to_bytes
from src.consensus.pot_iterations import calculate_min_iters_from_iterations
from src.util.ws_message import create_payload


class FullNodeRpcApiHandler(AbstractRpcApiHandler):
    def __init__(self, full_node: FullNode, stop_cb: Callable):
        super().__init__(full_node, stop_cb, "chia_full_node")
        self.cached_blockchain_state: Optional[Dict] = None

    async def _state_changed(self, change: str):
        assert self.websocket is not None
        payloads = []
        if change == "block":
            data = await self.get_latest_block_headers({})
            payloads.append(
                create_payload(
                    "get_latest_block_headers", data, self.service_name, "wallet_ui"
                )
            )
            data = await self.get_blockchain_state({})
            payloads.append(
                create_payload(
                    "get_blockchain_state", data, self.service_name, "wallet_ui"
                )
            )
        else:
            await super()._state_changed(change)
            return
        try:
            for payload in payloads:
                await self.websocket.send_str(payload)
        except (BaseException) as e:
            try:
                self.log.warning(f"Sending data failed. Exception {type(e)}.")
            except BrokenPipeError:
                pass

    async def get_blockchain_state(self, request: Dict):
        """
        Returns a summary of the node's view of the blockchain.
        """
        tips: List[Header] = self.service.blockchain.get_current_tips()
        lca: Header = self.service.blockchain.lca_block
        sync_mode: bool = self.service.sync_store.get_sync_mode()
        difficulty: uint64 = self.service.blockchain.get_next_difficulty(lca)
        lca_block = await self.service.block_store.get_block(lca.header_hash)
        if lca_block is None:
            return None
        min_iters: uint64 = self.service.blockchain.get_next_min_iters(lca_block)
        ips: uint64 = min_iters // (
            self.service.constants["BLOCK_TIME_TARGET"]
            / self.service.constants["MIN_ITERS_PROPORTION"]
        )

        tip_hashes = []
        for tip in tips:
            tip_hashes.append(tip.header_hash)
        if sync_mode and self.service.sync_peers_handler is not None:
            sync_tip_height = len(self.service.sync_store.get_potential_hashes())
            sync_progress_height = self.service.sync_peers_handler.fully_validated_up_to
        else:
            sync_tip_height = 0
            sync_progress_height = uint32(0)

        if lca.height >= 1:
            newer_block_hex = lca.header_hash.hex()
            older_block_hex = self.service.blockchain.height_to_hash[
                max(1, lca.height - 100)
            ].hex()
            space = await self.get_network_space(
                {
                    "newer_block_header_hash": newer_block_hex,
                    "older_block_header_hash": older_block_hex,
                }
            )
        else:
            space = {"space": uint128(0)}
        assert space is not None
        response: Dict = {
            "success": True,
            "blockchain_state": {
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
                "space": space["space"],
            },
        }
        self.cached_blockchain_state = dict(response["blockchain_state"])
        return response

    async def get_block(self, request: Dict) -> Optional[Dict]:
        if "header_hash" not in request:
            return None
        header_hash = hexstr_to_bytes(request["header_hash"])

        block: Optional[FullBlock] = await self.service.block_store.get_block(
            header_hash
        )
        if block is None:
            return None

        return {"success": True, "block": block}

    async def get_header_by_height(self, request: Dict) -> Optional[Dict]:
        if "height" not in request:
            return None
        height = request["height"]
        header_height = uint32(int(height))
        header_hash: Optional[bytes32] = self.service.blockchain.height_to_hash.get(
            header_height, None
        )
        if header_hash is None:
            return None
        header: Header = self.service.blockchain.headers[header_hash]
        return {"success": True, "header": header}

    async def get_header(self, request: Dict):
        if "header_hash" not in request:
            return None
        header_hash_str = request["header_hash"]
        header_hash = hexstr_to_bytes(header_hash_str)
        header: Optional[Header] = self.service.blockchain.headers.get(
            header_hash, None
        )
        return {"success": True, "header": header}

    async def get_unfinished_block_headers(self, request: Dict) -> Optional[Dict]:
        if "height" not in request:
            return None
        height = request["height"]
        response_headers: List[Header] = []
        for block in (
            await self.service.full_node_store.get_unfinished_blocks()
        ).values():
            if block.height == height:
                response_headers.append(block.header)
        return {"success": True, "headers": response_headers}

    async def get_latest_block_headers(self, request: Dict) -> Optional[Dict]:
        headers: Dict[bytes32, Header] = {}
        tips = self.service.blockchain.tips
        lca_hash = self.service.blockchain.lca_block.header_hash
        heights = []
        seen_lca = False
        for tip in tips:
            current = tip
            heights.append(current.height + 1)
            headers[current.header_hash] = current
            i = 0
            while True:
                # Returns blocks up to the LCA, and at least 10 blocks from the tip
                if current.header_hash == lca_hash:
                    seen_lca = True
                if seen_lca and i > 10:
                    break
                if current.height == 0:
                    break
                header: Optional[Header] = self.service.blockchain.headers.get(
                    current.prev_header_hash, None
                )
                assert header is not None
                headers[header.header_hash] = header
                current = header
                i += 1

        all_unfinished = {}
        for h in heights:
            unfinished_dict = await self.get_unfinished_block_headers({"height": h})
            assert unfinished_dict is not None
            for header in unfinished_dict["headers"]:
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
            await self.get_blockchain_state({})
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
            prev_header = self.service.blockchain.headers.get(header.prev_header_hash)
            if prev_header is not None:
                iter = header.data.total_iters - prev_header.data.total_iters
                time_add = int(iter / ips)
                header_dict["data"]["finish_time"] = header.data.timestamp + time_add
                unfinished_with_meta.append(header_dict)

        unfinished_with_meta.extend(finished_with_meta)

        return {"success": True, "latest_blocks": unfinished_with_meta}

    async def get_total_miniters(self, newer_block, older_block) -> Optional[uint64]:
        """
        Calculates the sum of min_iters from all blocks starting from
        old and up to and including new_block, but not including old_block.
        """
        older_block_parent = await self.service.block_store.get_block(
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
            if (
                curr_h % self.service.constants["DIFFICULTY_EPOCH"]
            ) == self.service.constants["DIFFICULTY_DELAY"]:
                curr_b_header_hash = self.service.blockchain.height_to_hash.get(
                    uint32(int(curr_h))
                )
                if curr_b_header_hash is None:
                    return None
                curr_b_block = await self.service.block_store.get_block(
                    curr_b_header_hash
                )
                if curr_b_block is None or curr_b_block.proof_of_time is None:
                    return None
                curr_parent = await self.service.block_store.get_block(
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

        return total_mi

    async def get_network_space(self, request: Dict) -> Optional[Dict]:
        """
        Retrieves an estimate of total space validating the chain
        between two block header hashes.
        """
        if (
            "newer_block_header_hash" not in request
            or "older_block_header_hash" not in request
        ):
            return None
        newer_block_hex = request["newer_block_header_hash"]
        older_block_hex = request["older_block_header_hash"]

        newer_block_bytes = hexstr_to_bytes(newer_block_hex)
        older_block_bytes = hexstr_to_bytes(older_block_hex)

        newer_block = await self.service.block_store.get_block(newer_block_bytes)
        if newer_block is None:
            raise web.HTTPNotFound()
        older_block = await self.service.block_store.get_block(older_block_bytes)
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
        return {"success": True, "space": uint128(int(network_space_bytes_estimate))}

    async def get_unspent_coins(self, request: Dict) -> Optional[Dict]:
        """
        Retrieves the unspent coins for a given puzzlehash.
        """
        if "puzzle_hash" not in request:
            return None
        puzzle_hash = hexstr_to_bytes(request["puzzle_hash"])
        header_hash = request.get("header_hash", None)

        if header_hash is not None:
            header_hash = bytes32(hexstr_to_bytes(header_hash))
            header = self.service.blockchain.headers.get(header_hash)
        else:
            header = None

        coin_records = await self.service.blockchain.coin_store.get_coin_records_by_puzzle_hash(
            puzzle_hash, header
        )

        return {"success": True, "coin_records": coin_records}

    async def get_heaviest_block_seen(self, request: Dict) -> Optional[Dict]:
        tips: List[Header] = self.service.blockchain.get_current_tips()
        tip_weights = [tip.weight for tip in tips]
        i = tip_weights.index(max(tip_weights))
        max_tip: Header = tips[i]
        if self.service.sync_store.get_sync_mode():
            potential_tips = self.service.sync_store.get_potential_tips_tuples()
            for _, pot_block in potential_tips:
                if pot_block.weight > max_tip.weight:
                    max_tip = pot_block.header
        return {"success": True, "tip": max_tip}


async def start_full_node_rpc_server(
    full_node: FullNode, stop_node_cb: Callable, rpc_port: uint16
):
    handler = FullNodeRpcApiHandler(full_node, stop_node_cb)
    routes = {
        "/get_blockchain_state": handler.get_blockchain_state,
        "/get_block": handler.get_block,
        "/get_header_by_height": handler.get_header_by_height,
        "/get_header": handler.get_header,
        "/get_unfinished_block_headers": handler.get_unfinished_block_headers,
        "/get_network_space": handler.get_network_space,
        "/get_unspent_coins": handler.get_unspent_coins,
        "/get_heaviest_block_seen": handler.get_heaviest_block_seen,
    }
    cleanup = await start_rpc_server(handler, rpc_port, routes)
    return cleanup


AbstractRpcApiHandler.register(FullNodeRpcApiHandler)
