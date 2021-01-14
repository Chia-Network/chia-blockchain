import time

from src.consensus.sub_block_record import SubBlockRecord
from src.full_node.full_node import FullNode
from typing import Callable, List, Optional, Dict

from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.types.unfinished_header_block import UnfinishedHeaderBlock
from src.util.byte_types import hexstr_to_bytes
from src.util.ints import uint64, uint32, uint128
from src.util.ws_message import create_payload
from src.consensus.pos_quality import UI_ACTUAL_SPACE_CONSTANT_FACTOR


class FullNodeRpcApi:
    def __init__(self, api: FullNode):
        self.service = api
        self.full_node = api
        self.service_name = "chia_full_node"
        self.cached_blockchain_state: Optional[Dict] = None

    def get_routes(self) -> Dict[str, Callable]:
        return {
            "/get_blockchain_state": self.get_blockchain_state,
            "/get_sub_block": self.get_sub_block,
            "/get_sub_block_record_by_sub_height": self.get_sub_block_record_by_sub_height,
            "/get_sub_block_record": self.get_sub_block_record,
            "/get_sub_block_records": self.get_sub_block_records,
            "/get_unfinished_sub_block_headers": self.get_unfinished_sub_block_headers,
            "/get_network_space": self.get_network_space,
            "/get_unspent_coins": self.get_unspent_coins,
            "/get_additions_and_removals": self.get_additions_and_removals,
            "/get_blocks": self.get_blocks,
        }

    async def _state_changed(self, change: str) -> List[Dict]:
        payloads = []
        if change == "new_peak":
            data = await self.get_blockchain_state({})
            assert data is not None
            payloads.append(
                create_payload(
                    "get_blockchain_state",
                    data,
                    self.service_name,
                    "wallet_ui",
                    string=False,
                )
            )
            return payloads
        return []

    async def get_blockchain_state(self, _request: Dict):
        """
        Returns a summary of the node's view of the blockchain.
        """
        full_peak: Optional[FullBlock] = await self.service.blockchain.get_block_peak()

        if full_peak is not None and full_peak.height > 0:
            if full_peak.header_hash in self.service.blockchain.sub_blocks:
                sub_block: SubBlockRecord = self.service.blockchain.sub_blocks[full_peak.header_hash]
                sub_slot_iters = sub_block.sub_slot_iters
            else:
                sub_slot_iters = self.service.constants.SUB_SLOT_ITERS_STARTING
            difficulty = uint64(
                full_peak.weight - self.service.blockchain.sub_blocks[full_peak.prev_header_hash].weight
            )
        else:
            difficulty = self.service.constants.DIFFICULTY_STARTING
            sub_slot_iters = self.service.constants.SUB_SLOT_ITERS_STARTING

        sync_mode: bool = self.service.sync_store.get_sync_mode()

        if sync_mode:
            max_pp = 0
            for _, potential_peak_tuple in self.service.sync_store.potential_peaks.items():
                peak_h, peak_w = potential_peak_tuple
                if peak_h > max_pp:
                    max_pp = peak_h
            sync_tip_height = max_pp
            sync_tip_sub_height = max_pp
            if full_peak is not None:
                sync_progress_sub_height = full_peak.sub_block_height
                sync_progress_height = full_peak.height
            else:
                sync_progress_sub_height = 0
                sync_progress_height = 0
        else:
            sync_tip_height = 0
            sync_tip_sub_height = 0
            sync_progress_sub_height = 0
            sync_progress_height = uint32(0)

        if full_peak is not None and full_peak.height > 1:
            newer_block_hex = full_peak.header_hash.hex()
            older_block_hex = self.service.blockchain.sub_height_to_hash[
                uint32(max(1, full_peak.sub_block_height - 1000))
            ].hex()
            space = await self.get_network_space(
                {"newer_block_header_hash": newer_block_hex, "older_block_header_hash": older_block_hex}
            )
        else:
            space = {"space": uint128(0)}

        now = time.time()
        if (
            full_peak is None
            or full_peak.foliage_block is None
            or full_peak.foliage_block.timestamp < now - 60 * 10
            or sync_mode
        ):
            synced = False
        else:
            synced = True

        assert space is not None
        response: Dict = {
            "blockchain_state": {
                "peak": full_peak,
                "sync": {
                    "sync_mode": sync_mode,
                    "synced": synced,
                    "sync_tip_height": sync_tip_height,
                    "sync_tip_sub_height": sync_tip_sub_height,
                    "sync_progress_height": sync_progress_height,
                    "sync_progress_sub_height": sync_progress_sub_height,
                },
                "difficulty": difficulty,
                "sub_slot_iters": sub_slot_iters,
                "space": space["space"],
            },
        }
        self.cached_blockchain_state = dict(response["blockchain_state"])
        return response

    async def get_sub_block(self, request: Dict) -> Optional[Dict]:
        if "header_hash" not in request:
            raise ValueError("No header_hash in request")
        header_hash = hexstr_to_bytes(request["header_hash"])

        block: Optional[FullBlock] = await self.service.block_store.get_full_block(header_hash)
        if block is None:
            raise ValueError(f"Block {header_hash.hex()} not found")

        return {"sub_block": block}

    async def get_blocks(self, request: Dict) -> Optional[Dict]:
        if "start" not in request:
            raise ValueError("No start in request")
        if "end" not in request:
            raise ValueError("No end in request")
        exclude_hh = False
        if "exclude_header_hash" in request:
            exclude_hh = request["exclude_header_hash"]

        start = int(request["start"])
        end = int(request["end"])
        block_range = []
        for a in range(start, end):
            block_range.append(uint32(a))
        blocks: List[FullBlock] = await self.service.block_store.get_full_blocks_at_height(block_range)
        json_blocks = []
        for block in blocks:
            json = block.to_json_dict()
            if not exclude_hh:
                json["header_hash"] = block.header_hash.hex()
            json_blocks.append(json)
        return {"blocks": json_blocks}

    async def get_sub_block_records(self, request: Dict) -> Optional[Dict]:
        if "start" not in request:
            raise ValueError("No start in request")
        if "end" not in request:
            raise ValueError("No end in request")

        start = int(request["start"])
        end = int(request["end"])
        records = []
        for a in range(start, end):
            header_hash: Optional[bytes32] = self.service.blockchain.sub_height_to_hash.get(uint32(a), None)
            if header_hash is None:
                continue
            record: Optional[SubBlockRecord] = self.service.blockchain.sub_blocks.get(header_hash, None)
            full = await self.service.blockchain.block_store.get_full_block(header_hash)
            if record is None:
                # Fetch from DB
                record = await self.service.blockchain.block_store.get_sub_block_record(header_hash)
            if record is None or full is None:
                raise ValueError(f"Sub block {header_hash.hex()} does not exist")

            json = record.to_json_dict()
            if full.transactions_info is not None:
                json["reward_claims_incorporated"] = full.transactions_info.reward_claims_incorporated
            else:
                json["reward_claims_incorporated"] = []
            records.append(json)
        return {"sub_block_records": records}

    async def get_sub_block_record_by_sub_height(self, request: Dict) -> Optional[Dict]:
        if "sub_height" not in request:
            raise ValueError("No sub_height in request")
        sub_block_height = request["sub_height"]
        header_height = uint32(int(sub_block_height))
        header_hash: Optional[bytes32] = self.service.blockchain.sub_height_to_hash.get(header_height, None)
        if header_hash is None:
            raise ValueError(f"Sub block height {sub_block_height} not found in chain")
        record: Optional[SubBlockRecord] = self.service.blockchain.sub_blocks.get(header_hash, None)
        if record is None:
            # Fetch from DB
            record = await self.service.blockchain.block_store.get_sub_block_record(header_hash)
        if record is None:
            raise ValueError(f"Sub block {header_hash} does not exist")
        return {"sub_block_record": record}

    async def get_sub_block_record(self, request: Dict):
        if "header_hash" not in request:
            raise ValueError("header_hash not in request")
        header_hash_str = request["header_hash"]
        header_hash = hexstr_to_bytes(header_hash_str)
        record: Optional[SubBlockRecord] = self.service.blockchain.sub_blocks.get(header_hash, None)
        if record is None:
            # Fetch from DB
            record = await self.service.blockchain.block_store.get_sub_block_record(header_hash)
        if record is None:
            raise ValueError(f"Sub block {header_hash.hex()} does not exist")
        return {"sub_block_record": record}

    async def get_unfinished_sub_block_headers(self, request: Dict) -> Optional[Dict]:

        peak: Optional[SubBlockRecord] = self.service.blockchain.get_peak()
        if peak is None:
            return {"headers": []}

        response_headers: List[UnfinishedHeaderBlock] = []
        for ub_sub_height, block in (self.service.full_node_store.get_unfinished_blocks()).values():
            if ub_sub_height == peak.sub_block_height:
                unfinished_header_block = UnfinishedHeaderBlock(
                    block.finished_sub_slots,
                    block.reward_chain_sub_block,
                    block.challenge_chain_sp_proof,
                    block.reward_chain_sp_proof,
                    block.foliage_sub_block,
                    block.foliage_block,
                    b"",
                )
                response_headers.append(unfinished_header_block)
        return {"headers": response_headers}

    async def get_network_space(self, request: Dict) -> Optional[Dict]:
        """
        Retrieves an estimate of total space validating the chain
        between two block header hashes.
        """
        if "newer_block_header_hash" not in request or "older_block_header_hash" not in request:
            raise ValueError("Invalid request. newer_block_header_hash and older_block_header_hash required")
        newer_block_hex = request["newer_block_header_hash"]
        older_block_hex = request["older_block_header_hash"]

        if newer_block_hex == older_block_hex:
            raise ValueError("New and old must not be the same")

        newer_block_bytes = hexstr_to_bytes(newer_block_hex)
        older_block_bytes = hexstr_to_bytes(older_block_hex)

        newer_block = await self.service.block_store.get_sub_block_record(newer_block_bytes)
        if newer_block is None:
            raise ValueError("Newer block not found")
        older_block = await self.service.block_store.get_sub_block_record(older_block_bytes)
        if older_block is None:
            raise ValueError("Newer block not found")
        delta_weight = newer_block.weight - older_block.weight

        delta_iters = newer_block.total_iters - older_block.total_iters
        weight_div_iters = delta_weight / delta_iters
        additional_difficulty_constant = 2 ** 25
        eligible_plots_filter_multiplier = 2 ** self.service.constants.NUMBER_ZERO_BITS_PLOT_FILTER
        network_space_bytes_estimate = (
            UI_ACTUAL_SPACE_CONSTANT_FACTOR
            * weight_div_iters
            * additional_difficulty_constant
            * eligible_plots_filter_multiplier
        )
        return {"space": uint128(int(network_space_bytes_estimate))}

    async def get_unspent_coins(self, request: Dict) -> Optional[Dict]:
        """
        Retrieves the unspent coins for a given puzzlehash.
        """
        if "puzzle_hash" not in request:
            raise ValueError("Puzzle hash not in request")
        puzzle_hash = hexstr_to_bytes(request["puzzle_hash"])

        coin_records = await self.service.blockchain.coin_store.get_coin_records_by_puzzle_hash(puzzle_hash)

        return {"coin_records": coin_records}

    async def get_additions_and_removals(self, request: Dict) -> Optional[Dict]:
        if "header_hash" not in request:
            raise ValueError("No header_hash in request")
        header_hash = hexstr_to_bytes(request["header_hash"])

        block: Optional[FullBlock] = await self.service.block_store.get_full_block(header_hash)
        if block is None:
            raise ValueError(f"Block {header_hash.hex()} not found")
        reward_additions = block.get_included_reward_coins()

        # TODO: optimize
        tx_removals, tx_additions = await block.tx_removals_and_additions()
        removal_records = []
        addition_records = []
        for tx_removal in tx_removals:
            removal_records.append(await self.service.coin_store.get_coin_record(tx_removal))
        for tx_addition in tx_additions + list(reward_additions):
            addition_records.append(await self.service.coin_store.get_coin_record(tx_addition.name()))
        return {"additions": addition_records, "removals": removal_records}
