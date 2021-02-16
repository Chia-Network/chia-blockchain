from src.consensus.block_record import BlockRecord
from src.full_node.full_node import FullNode
from typing import Callable, List, Optional, Dict

from src.types.full_block import FullBlock
from src.types.blockchain_format.sized_bytes import bytes32
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
            "/get_block": self.get_block,
            "/get_block_record_by_height": self.get_block_record_by_height,
            "/get_block_record": self.get_block_record,
            "/get_block_records": self.get_block_records,
            "/get_unfinished_block_headers": self.get_unfinished_block_headers,
            "/get_network_space": self.get_network_space,
            "/get_unspent_coins": self.get_unspent_coins,
            "/get_additions_and_removals": self.get_additions_and_removals,
            "/get_blocks": self.get_blocks,
            "/get_initial_freeze_period": self.get_initial_freeze_period,
        }

    async def _state_changed(self, change: str) -> List[Dict]:
        payloads = []
        if change == "new_peak" or change == "sync_mode":
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

    async def get_initial_freeze_period(self):
        freeze_period = self.service.constants.INITIAL_FREEZE_PERIOD
        return {"INITIAL_FREEZE_PERIOD": freeze_period}

    async def get_blockchain_state(self, _request: Dict):
        """
        Returns a summary of the node's view of the blockchain.
        """
        peak: Optional[BlockRecord] = self.service.blockchain.get_peak()

        if peak is not None and peak.height > 0:
            difficulty = uint64(peak.weight - self.service.blockchain.block_record(peak.prev_hash).weight)
            sub_slot_iters = peak.sub_slot_iters
        else:
            difficulty = self.service.constants.DIFFICULTY_STARTING
            sub_slot_iters = self.service.constants.SUB_SLOT_ITERS_STARTING

        sync_mode: bool = self.service.sync_store.get_sync_mode()

        sync_tip_height: Optional[uint32] = uint32(0)
        if sync_mode:
            if self.service.sync_store.get_sync_target_height() is not None:
                sync_tip_height = self.service.sync_store.get_sync_target_height()
                assert sync_tip_height is not None
            if peak is not None:
                sync_progress_height: uint32 = peak.height
            else:
                sync_progress_height = uint32(0)
        else:
            sync_progress_height = uint32(0)

        if peak is not None and peak.height > 1:
            newer_block_hex = peak.header_hash.hex()
            header_hash = self.service.blockchain.height_to_hash(uint32(max(1, peak.height - 1000)))
            assert header_hash is not None
            older_block_hex = header_hash.hex()
            space = await self.get_network_space(
                {"newer_block_header_hash": newer_block_hex, "older_block_header_hash": older_block_hex}
            )
        else:
            space = {"space": uint128(0)}

        synced = await self.service.synced()
        if self.full_node.mempool_manager is not None:
            mempool_size = len(self.full_node.mempool_manager.mempool.spends)
        else:
            mempool_size = 0

        assert space is not None
        response: Dict = {
            "blockchain_state": {
                "peak": peak,
                "sync": {
                    "sync_mode": sync_mode,
                    "synced": synced,
                    "sync_tip_height": sync_tip_height,
                    "sync_progress_height": sync_progress_height,
                },
                "difficulty": difficulty,
                "sub_slot_iters": sub_slot_iters,
                "space": space["space"],
                "mempool_size": mempool_size,
            },
        }
        self.cached_blockchain_state = dict(response["blockchain_state"])
        return response

    async def get_block(self, request: Dict) -> Optional[Dict]:
        if "header_hash" not in request:
            raise ValueError("No header_hash in request")
        header_hash = hexstr_to_bytes(request["header_hash"])

        block: Optional[FullBlock] = await self.service.block_store.get_full_block(header_hash)
        if block is None:
            raise ValueError(f"Block {header_hash.hex()} not found")

        return {"block": block}

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
        blocks: List[FullBlock] = await self.service.block_store.get_full_blocks_at(block_range)
        json_blocks = []
        for block in blocks:
            json = block.to_json_dict()
            if not exclude_hh:
                json["header_hash"] = block.header_hash.hex()
            json_blocks.append(json)
        return {"blocks": json_blocks}

    async def get_block_records(self, request: Dict) -> Optional[Dict]:
        if "start" not in request:
            raise ValueError("No start in request")
        if "end" not in request:
            raise ValueError("No end in request")

        start = int(request["start"])
        end = int(request["end"])
        records = []
        peak_height = self.full_node.blockchain.get_peak_height()
        if peak_height is None:
            raise ValueError("Peak is None")

        for a in range(start, end):
            if peak_height < uint32(a):
                self.full_node.log.warning("requested block is higher than known peak ")
                break
            header_hash: bytes32 = self.service.blockchain.height_to_hash(uint32(a))
            record: Optional[BlockRecord] = self.service.blockchain.try_block_record(header_hash)
            if record is None:
                # Fetch from DB
                record = await self.service.blockchain.block_store.get_block_record(header_hash)
            if record is None:
                raise ValueError(f"Block {header_hash.hex()} does not exist")

            records.append(record)
        return {"block_records": records}

    async def get_block_record_by_height(self, request: Dict) -> Optional[Dict]:
        if "height" not in request:
            raise ValueError("No height in request")
        height = request["height"]
        header_height = uint32(int(height))
        peak_height = self.service.blockchain.get_peak_height()
        if peak_height is None or header_height > peak_height:
            raise ValueError(f"Block height {height} not found in chain")
        header_hash: Optional[bytes32] = self.service.blockchain.height_to_hash(header_height)
        if header_hash is None:
            raise ValueError(f"Block hash {height} not found in chain")
        record: Optional[BlockRecord] = self.service.blockchain.try_block_record(header_hash)
        if record is None:
            # Fetch from DB
            record = await self.service.blockchain.block_store.get_block_record(header_hash)
        if record is None:
            raise ValueError(f"Block {header_hash} does not exist")
        return {"block_record": record}

    async def get_block_record(self, request: Dict):
        if "header_hash" not in request:
            raise ValueError("header_hash not in request")
        header_hash_str = request["header_hash"]
        header_hash = hexstr_to_bytes(header_hash_str)
        record: Optional[BlockRecord] = self.service.blockchain.try_block_record(header_hash)
        if record is None:
            # Fetch from DB
            record = await self.service.blockchain.block_store.get_block_record(header_hash)
        if record is None:
            raise ValueError(f"Block {header_hash.hex()} does not exist")

        return {"block_record": record}

    async def get_unfinished_block_headers(self, request: Dict) -> Optional[Dict]:

        peak: Optional[BlockRecord] = self.service.blockchain.get_peak()
        if peak is None:
            return {"headers": []}

        response_headers: List[UnfinishedHeaderBlock] = []
        for ub_height, block in (self.service.full_node_store.get_unfinished_blocks()).values():
            if ub_height == peak.height:
                unfinished_header_block = UnfinishedHeaderBlock(
                    block.finished_sub_slots,
                    block.reward_chain_block,
                    block.challenge_chain_sp_proof,
                    block.reward_chain_sp_proof,
                    block.foliage,
                    block.foliage_transaction_block,
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

        newer_block = await self.service.block_store.get_block_record(newer_block_bytes)
        if newer_block is None:
            raise ValueError("Newer block not found")
        older_block = await self.service.block_store.get_block_record(older_block_bytes)
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
        tx_removals, tx_additions = block.tx_removals_and_additions()
        removal_records = []
        addition_records = []
        for tx_removal in tx_removals:
            removal_records.append(await self.service.coin_store.get_coin_record(tx_removal))
        for tx_addition in tx_additions + list(reward_additions):
            addition_records.append(await self.service.coin_store.get_coin_record(tx_addition.name()))
        return {"additions": addition_records, "removals": removal_records}
