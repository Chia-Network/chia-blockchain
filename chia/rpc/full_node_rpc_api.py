from typing import Any, Callable, Dict, List, Optional, Set

import blspy
from blspy import G1Element, G2Element

from chia.consensus.block_record import BlockRecord
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.pos_quality import UI_ACTUAL_SPACE_CONSTANT_FACTOR
from chia.full_node.full_node import FullNode
from chia.full_node.mempool_check_conditions import get_puzzle_and_solution_for_coin
from chia.rpc.cat_utils import get_cat_puzzle_hash
from chia.types.announcement import Announcement
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.types.unfinished_header_block import UnfinishedHeaderBlock
from chia.util.byte_types import hexstr_to_bytes
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
from chia.util.ws_message import WsRpcMessage, create_payload_dict
from chia.types.blockchain_format.coin import Coin
from chia.wallet.cc_wallet.cc_utils import match_cat_puzzle
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk
from chia.wallet.wallet import Wallet
from chia.wallet.puzzles.cc_loader import CC_MOD


class FullNodeRpcApi:
    def __init__(self, service: FullNode):
        self.service = service
        self.service_name = "chia_full_node"
        self.cached_blockchain_state: Optional[Dict] = None

    def get_routes(self) -> Dict[str, Callable]:
        return {
            # Blockchain
            "/get_blockchain_state": self.get_blockchain_state,
            "/get_block": self.get_block,
            "/get_blocks": self.get_blocks,
            "/get_block_record_by_height": self.get_block_record_by_height,
            "/get_block_record": self.get_block_record,
            "/get_block_records": self.get_block_records,
            "/get_unfinished_block_headers": self.get_unfinished_block_headers,
            "/get_network_space": self.get_network_space,
            "/get_additions_and_removals": self.get_additions_and_removals,
            # this function is just here for backwards-compatibility. It will probably
            # be removed in the future
            "/get_initial_freeze_period": self.get_initial_freeze_period,
            "/get_network_info": self.get_network_info,
            "/get_recent_signage_point_or_eos": self.get_recent_signage_point_or_eos,
            # Coins
            "/get_coin_id": self.get_coin_id,
            "/get_coin_records_in_range": self.get_coin_records_in_range,
            "/get_coin_records_by_puzzle_hash": self.get_coin_records_by_puzzle_hash,
            "/get_coin_records_by_puzzle_hashes": self.get_coin_records_by_puzzle_hashes,
            "/get_coin_record_by_name": self.get_coin_record_by_name,
            "/get_coin_records_by_names": self.get_coin_records_by_names,
            "/get_coin_records_by_parent_ids": self.get_coin_records_by_parent_ids,
            "/create_unsigned_transaction": self.create_unsigned_transaction,
            "/puzzle_hash_for_pk": self.puzzle_hash_for_pk,
            "/push_tx": self.push_tx,
            "/get_puzzle_and_solution": self.get_puzzle_and_solution,
            "/is_cat_coin": self.is_cat_coin,
            "/are_cat_coins": self.are_cat_coins,
            "/get_cat_puzzle_hash": self.get_cat_puzzle_hash,
            # Mempool
            "/get_all_mempool_tx_ids": self.get_all_mempool_tx_ids,
            "/get_all_mempool_items": self.get_all_mempool_items,
            "/get_mempool_item_by_tx_id": self.get_mempool_item_by_tx_id,
        }

    async def _state_changed(self, change: str) -> List[WsRpcMessage]:
        payloads = []
        if change == "new_peak" or change == "sync_mode":
            data = await self.get_blockchain_state({})
            assert data is not None
            payloads.append(
                create_payload_dict(
                    "get_blockchain_state",
                    data,
                    self.service_name,
                    "wallet_ui",
                )
            )
            return payloads
        return []

    # this function is just here for backwards-compatibility. It will probably
    # be removed in the future
    async def get_initial_freeze_period(self, _: Dict):
        # Mon May 03 2021 17:00:00 GMT+0000
        return {"INITIAL_FREEZE_END_TIMESTAMP": 1620061200}

    async def get_blockchain_state(self, _request: Dict):
        """
        Returns a summary of the node's view of the blockchain.
        """
        if self.service.initialized is False:
            res: Dict = {
                "blockchain_state": {
                    "peak": None,
                    "genesis_challenge_initialized": self.service.initialized,
                    "sync": {
                        "sync_mode": False,
                        "synced": False,
                        "sync_tip_height": 0,
                        "sync_progress_height": 0,
                    },
                    "difficulty": 0,
                    "sub_slot_iters": 0,
                    "space": 0,
                    "mempool_size": 0,
                },
            }
            return res
        peak: Optional[BlockRecord] = self.service.blockchain.get_peak()

        if peak is not None and peak.height > 0:
            difficulty = uint64(peak.weight - self.service.blockchain.block_record(peak.prev_hash).weight)
            sub_slot_iters = peak.sub_slot_iters
        else:
            difficulty = self.service.constants.DIFFICULTY_STARTING
            sub_slot_iters = self.service.constants.SUB_SLOT_ITERS_STARTING

        sync_mode: bool = self.service.sync_store.get_sync_mode() or self.service.sync_store.get_long_sync()

        sync_tip_height: Optional[uint32] = uint32(0)
        if sync_mode:
            if self.service.sync_store.get_sync_target_height() is not None:
                sync_tip_height = self.service.sync_store.get_sync_target_height()
                assert sync_tip_height is not None
            if peak is not None:
                sync_progress_height: uint32 = peak.height
                # Don't display we're syncing towards 0, instead show 'Syncing height/height'
                # until sync_store retrieves the correct number.
                if sync_tip_height == uint32(0):
                    sync_tip_height = peak.height
            else:
                sync_progress_height = uint32(0)
        else:
            sync_progress_height = uint32(0)

        if peak is not None and peak.height > 1:
            newer_block_hex = peak.header_hash.hex()
            # Average over the last day
            header_hash = self.service.blockchain.height_to_hash(uint32(max(1, peak.height - 4608)))
            assert header_hash is not None
            older_block_hex = header_hash.hex()
            space = await self.get_network_space(
                {"newer_block_header_hash": newer_block_hex, "older_block_header_hash": older_block_hex}
            )
        else:
            space = {"space": uint128(0)}

        if self.service.mempool_manager is not None:
            mempool_size = len(self.service.mempool_manager.mempool.spends)
        else:
            mempool_size = 0
        if self.service.server is not None:
            is_connected = len(self.service.server.get_full_node_connections()) > 0
        else:
            is_connected = False
        synced = await self.service.synced() and is_connected

        assert space is not None
        response: Dict = {
            "blockchain_state": {
                "peak": peak,
                "genesis_challenge_initialized": self.service.initialized,
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

    async def get_network_info(self, request: Dict):
        network_name = self.service.config["selected_network"]
        address_prefix = self.service.config["network_overrides"]["config"][network_name]["address_prefix"]
        return {"network_name": network_name, "network_prefix": address_prefix}

    async def get_recent_signage_point_or_eos(self, request: Dict):
        if "sp_hash" not in request:
            challenge_hash: bytes32 = hexstr_to_bytes(request["challenge_hash"])
            # This is the case of getting an end of slot
            eos_tuple = self.service.full_node_store.recent_eos.get(challenge_hash)
            if not eos_tuple:
                raise ValueError(f"Did not find eos {challenge_hash.hex()} in cache")
            eos, time_received = eos_tuple

            # If it's still in the full node store, it's not reverted
            if self.service.full_node_store.get_sub_slot(eos.challenge_chain.get_hash()):
                return {"eos": eos, "time_received": time_received, "reverted": False}

            # Otherwise we can backtrack from peak to find it in the blockchain
            curr: Optional[BlockRecord] = self.service.blockchain.get_peak()
            if curr is None:
                raise ValueError("No blocks in the chain")

            number_of_slots_searched = 0
            while number_of_slots_searched < 10:
                if curr.first_in_sub_slot:
                    assert curr.finished_challenge_slot_hashes is not None
                    if curr.finished_challenge_slot_hashes[-1] == eos.challenge_chain.get_hash():
                        # Found this slot in the blockchain
                        return {"eos": eos, "time_received": time_received, "reverted": False}
                    number_of_slots_searched += len(curr.finished_challenge_slot_hashes)
                curr = self.service.blockchain.try_block_record(curr.prev_hash)
                if curr is None:
                    # Got to the beginning of the blockchain without finding the slot
                    return {"eos": eos, "time_received": time_received, "reverted": True}

            # Backtracked through 10 slots but still did not find it
            return {"eos": eos, "time_received": time_received, "reverted": True}

        # Now we handle the case of getting a signage point
        sp_hash: bytes32 = hexstr_to_bytes(request["sp_hash"])
        sp_tuple = self.service.full_node_store.recent_signage_points.get(sp_hash)
        if sp_tuple is None:
            raise ValueError(f"Did not find sp {sp_hash.hex()} in cache")

        sp, time_received = sp_tuple

        # If it's still in the full node store, it's not reverted
        if self.service.full_node_store.get_signage_point(sp_hash):
            return {"signage_point": sp, "time_received": time_received, "reverted": False}

        # Otherwise we can backtrack from peak to find it in the blockchain
        rc_challenge: bytes32 = sp.rc_vdf.challenge
        next_b: Optional[BlockRecord] = None
        curr_b_optional: Optional[BlockRecord] = self.service.blockchain.get_peak()
        assert curr_b_optional is not None
        curr_b: BlockRecord = curr_b_optional

        for _ in range(200):
            sp_total_iters = sp.cc_vdf.number_of_iterations + curr_b.ip_sub_slot_total_iters(self.service.constants)
            if curr_b.reward_infusion_new_challenge == rc_challenge:
                if next_b is None:
                    return {"signage_point": sp, "time_received": time_received, "reverted": False}
                next_b_total_iters = next_b.ip_sub_slot_total_iters(self.service.constants) + next_b.ip_iters(
                    self.service.constants
                )

                return {
                    "signage_point": sp,
                    "time_received": time_received,
                    "reverted": sp_total_iters > next_b_total_iters,
                }
            if curr_b.finished_reward_slot_hashes is not None:
                assert curr_b.finished_challenge_slot_hashes is not None
                for eos_rc in curr_b.finished_challenge_slot_hashes:
                    if eos_rc == rc_challenge:
                        if next_b is None:
                            return {"signage_point": sp, "time_received": time_received, "reverted": False}
                        next_b_total_iters = next_b.ip_sub_slot_total_iters(self.service.constants) + next_b.ip_iters(
                            self.service.constants
                        )
                        return {
                            "signage_point": sp,
                            "time_received": time_received,
                            "reverted": sp_total_iters > next_b_total_iters,
                        }
            next_b = curr_b
            curr_b_optional = self.service.blockchain.try_block_record(curr_b.prev_hash)
            if curr_b_optional is None:
                break
            curr_b = curr_b_optional

        return {"signage_point": sp, "time_received": time_received, "reverted": True}

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
        peak_height = self.service.blockchain.get_peak_height()
        if peak_height is None:
            raise ValueError("Peak is None")

        for a in range(start, end):
            if peak_height < uint32(a):
                self.service.log.warning("requested block is higher than known peak ")
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
        for ub_height, block, _ in (self.service.full_node_store.get_unfinished_blocks()).values():
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
        additional_difficulty_constant = self.service.constants.DIFFICULTY_CONSTANT_FACTOR
        eligible_plots_filter_multiplier = 2 ** self.service.constants.NUMBER_ZERO_BITS_PLOT_FILTER
        network_space_bytes_estimate = (
            UI_ACTUAL_SPACE_CONSTANT_FACTOR
            * weight_div_iters
            * additional_difficulty_constant
            * eligible_plots_filter_multiplier
        )
        return {"space": uint128(int(network_space_bytes_estimate))}

    async def get_coin_records_by_puzzle_hash(self, request: Dict) -> Optional[Dict]:
        """
        Retrieves the coins for a given puzzlehash, by default returns unspent coins.
        """
        if "puzzle_hash" not in request:
            raise ValueError("Puzzle hash not in request")
        kwargs: Dict[str, Any] = {"include_spent_coins": False, "puzzle_hash": hexstr_to_bytes(request["puzzle_hash"])}
        if "start_height" in request:
            kwargs["start_height"] = uint32(request["start_height"])
        if "end_height" in request:
            kwargs["end_height"] = uint32(request["end_height"])

        if "include_spent_coins" in request:
            kwargs["include_spent_coins"] = request["include_spent_coins"]

        coin_records = await self.service.blockchain.coin_store.get_coin_records_by_puzzle_hash(**kwargs)

        return {"coin_records": coin_records}

    async def get_coin_id(self, request: Dict) -> Optional[Dict]:
        coin = Coin(
            parent_coin_info=bytes.fromhex(request["parent_coin_info"].lstrip("0x")),
            puzzle_hash=bytes.fromhex(request["puzzle_hash"].lstrip("0x")),
            amount=int(request["amount"]),
        )
        return {
            "coin_id": coin.name()
        }

    async def get_coin_records_in_range(self, request: Dict) -> Optional[Dict]:
        """
        Retrieves the coins in a range of block height
        """
        if not "start_height" in request:
            raise ValueError("start_height not in request")
        if not "end_height" in request:
            raise ValueError("end_height not in request")
        kwargs: Dict[str, Any] = {
            "start_height": uint32(request["start_height"]),
            "end_height": uint32(request["end_height"]),
        }
        if "include_spent_coins" in request:
            kwargs["include_spent_coins"] = request["include_spent_coins"]

        coin_records = await self.service.blockchain.coin_store.get_coin_records_in_range(**kwargs)
        return {"coin_records": coin_records}

    async def get_coin_records_by_puzzle_hashes(self, request: Dict) -> Optional[Dict]:
        """
        Retrieves the coins for a given puzzlehash, by default returns unspent coins.
        """
        if "puzzle_hashes" not in request:
            raise ValueError("Puzzle hashes not in request")
        kwargs: Dict[str, Any] = {
            "include_spent_coins": False,
            "puzzle_hashes": [hexstr_to_bytes(ph) for ph in request["puzzle_hashes"]],
        }
        if "start_height" in request:
            kwargs["start_height"] = uint32(request["start_height"])
        if "end_height" in request:
            kwargs["end_height"] = uint32(request["end_height"])

        if "include_spent_coins" in request:
            kwargs["include_spent_coins"] = request["include_spent_coins"]

        coin_records = await self.service.blockchain.coin_store.get_coin_records_by_puzzle_hashes(**kwargs)

        return {"coin_records": coin_records}

    async def get_coin_record_by_name(self, request: Dict) -> Optional[Dict]:
        """
        Retrieves a coin record by it's name.
        """
        if "name" not in request:
            raise ValueError("Name not in request")
        name = hexstr_to_bytes(request["name"])

        coin_record: Optional[CoinRecord] = await self.service.blockchain.coin_store.get_coin_record(name)
        if coin_record is None:
            raise ValueError(f"Coin record 0x{name.hex()} not found")

        return {"coin_record": coin_record}

    async def get_coin_records_by_names(self, request: Dict) -> Optional[Dict]:
        """
        Retrieves the coins for given coin IDs, by default returns unspent coins.
        """
        if "names" not in request:
            raise ValueError("Names not in request")
        kwargs: Dict[str, Any] = {
            "include_spent_coins": False,
            "names": [hexstr_to_bytes(name) for name in request["names"]],
        }
        if "start_height" in request:
            kwargs["start_height"] = uint32(request["start_height"])
        if "end_height" in request:
            kwargs["end_height"] = uint32(request["end_height"])

        if "include_spent_coins" in request:
            kwargs["include_spent_coins"] = request["include_spent_coins"]

        coin_records = await self.service.blockchain.coin_store.get_coin_records_by_names(**kwargs)

        return {"coin_records": coin_records}

    async def get_coin_records_by_parent_ids(self, request: Dict) -> Optional[Dict]:
        """
        Retrieves the coins for given parent coin IDs, by default returns unspent coins.
        """
        if "parent_ids" not in request:
            raise ValueError("Parent IDs not in request")
        kwargs: Dict[str, Any] = {
            "include_spent_coins": False,
            "parent_ids": [hexstr_to_bytes(ph) for ph in request["parent_ids"]],
        }
        if "start_height" in request:
            kwargs["start_height"] = uint32(request["start_height"])
        if "end_height" in request:
            kwargs["end_height"] = uint32(request["end_height"])

        if "include_spent_coins" in request:
            kwargs["include_spent_coins"] = request["include_spent_coins"]

        coin_records = await self.service.blockchain.coin_store.get_coin_records_by_parent_ids(**kwargs)

        return {"coin_records": coin_records}

    async def puzzle_hash_for_pk(self, request):
        pk = G1Element.from_bytes(hexstr_to_bytes(request["public_key"]))
        puzzle_hash = puzzle_for_pk(pk).get_tree_hash()
        if len(puzzle_hash) != 32:
            raise ValueError(f"Address must be 32 bytes. {puzzle_hash}")
        return {
            "puzzle_hash": puzzle_hash
        }
        
    # Make this method as independent from wallet state as possible
    async def _generate_unsigned_transaction(
            self,
            pk: G1Element,
            spend_amount: uint64,
            to_puzzle_hash: bytes32,
            fee: uint64 = uint64(0),
            coins: Set[Coin] = None,
            primaries: Optional[List[Dict[str, bytes32]]] = None,
        ) -> List[CoinSpend]:
        """
        Generates a unsigned transaction in form of List(Puzzle, Solutions)
        Note: this must be called under a wallet state manager lock
        """
        if primaries is None:
            total_amount = spend_amount + fee
        else:
            primaries = primaries.copy()
            primaries_amount = 0
            for prim in primaries:
                primaries_amount += prim["amount"]
            total_amount = spend_amount + fee + primaries_amount

        if coins is None or len(coins) == 0:
            raise ValueError("Need pre-selected coins")

        # Select coins that suffice total_amount
        selected_coins: List[Coin] = []
        total_selected_amount = 0
        for coin in coins:
            total_selected_amount += coin.amount
            assert coin not in selected_coins
            selected_coins.append(coin)

            if total_selected_amount >= total_amount:
                break
        if total_selected_amount < total_amount:
            raise ValueError(f"Not enough coins, total value {total_selected_amount}, need {total_amount}")

        change = total_selected_amount - total_amount
        assert change >= 0

        spends: List[CoinSpend] = []
        primary_announcement_hash: Optional[bytes32] = None
        for coin in selected_coins:
            puzzle: Program = puzzle_for_pk(pk)
            from_puzzle_hash = puzzle.get_tree_hash()
            if coin.puzzle_hash != from_puzzle_hash:
                raise ValueError(
                    f"Coin puzzle hash[{coin.puzzle_hash}] doesnt match: pk puzzle[{from_puzzle_hash}]"
                )

            # Only one coin creates outputs
            if primary_announcement_hash is None:
                if primaries is None:
                    primaries = [{"puzzlehash": to_puzzle_hash, "amount": spend_amount}]
                else:
                    primaries.append({"puzzlehash": to_puzzle_hash, "amount": spend_amount})
                if change > 0:
                    # Send the change back to the original owner
                    primaries.append({"puzzlehash": from_puzzle_hash, "amount": change})

                message_list: List[bytes32] = [c.name() for c in selected_coins]
                for primary in primaries:
                    message_list.append(Coin(coin.name(), primary["puzzlehash"], primary["amount"]).name())
                message: bytes32 = std_hash(b"".join(message_list))
                solution: Program = Wallet().make_solution(
                    primaries=primaries,
                    fee=fee,
                    coin_announcements={message},
                )
                primary_announcement_hash = Announcement(coin.name(), message).name()
            else:
                solution = Wallet().make_solution(coin_announcements_to_assert={primary_announcement_hash})

            spends.append(
                CoinSpend(
                    coin, SerializedProgram.from_bytes(bytes(puzzle)), SerializedProgram.from_bytes(bytes(solution))
                )
            )

        return spends

    async def create_unsigned_transaction(self, request):
        if "additions" not in request or len(request["additions"]) < 1:
            raise ValueError("Specify additions list")

        additions: List[Dict] = request["additions"]
        spend_amount: uint64 = uint64(additions[0]["amount"])
        assert spend_amount <= self.service.constants.MAX_COIN_AMOUNT

        to_puzzle_hash = hexstr_to_bytes(additions[0]["puzzle_hash"])
        if len(to_puzzle_hash) != 32:
            raise ValueError(f"Address must be 32 bytes. {to_puzzle_hash}")

        from_pk = G1Element.from_bytes(hexstr_to_bytes(request["from_pk"]))

        additional_outputs = []
        for addition in additions[1:]:
            receiver_ph = hexstr_to_bytes(addition["puzzle_hash"])
            if len(receiver_ph) != 32:
                raise ValueError(f"Address must be 32 bytes. {receiver_ph}")
            amount = uint64(addition["amount"])
            if amount > self.service.constants.MAX_COIN_AMOUNT:
                raise ValueError(f"Coin amount cannot exceed {self.service.constants.MAX_COIN_AMOUNT}")
            additional_outputs.append({"puzzlehash": receiver_ph, "amount": amount})

        fee = uint64(0)
        if "fee" in request:
            fee = uint64(request["fee"])

        if "coins" in request and len(request["coins"]) > 0:
            coins = set([Coin.from_json_dict(coin_json) for coin_json in request["coins"]])

        unsigned_tx = await self._generate_unsigned_transaction(
            from_pk, spend_amount, to_puzzle_hash, fee, coins=coins, primaries=additional_outputs
        )

        pk_list: List[blspy.G1Element] = []
        msg_list: List[bytes] = []
        if len(unsigned_tx) <= 0:
            raise ValueError("spends is zero")

        for coin_spend in unsigned_tx:
            # Get AGG_SIG conditions
            err, conditions_dict, _ = conditions_dict_for_solution(
                coin_spend.puzzle_reveal, coin_spend.solution, DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM
            )
            if err or conditions_dict is None:
                raise ValueError(f"Create Unsigned transaction failed, con:{conditions_dict}, error: {err}")

            for pk, msg in pkm_pairs_for_conditions_dict(conditions_dict, bytes(coin_spend.coin.name()), DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA):
                pk_list.append(pk)
                msg_list.append(msg)

        spend_bundle: SpendBundle = SpendBundle(unsigned_tx, G2Element())
        addition_coins = spend_bundle.additions()
        if len(addition_coins) <= 0:
            raise ValueError("addition_coins is empty")

        return {
            "solution": unsigned_tx,
            "pk_list": [bytes(pk).hex() for pk in pk_list],
            "msg_list": [msg.hex() for msg in msg_list],
            "addition_coin_ids": [ac.name() for ac in addition_coins],
        }

    async def push_tx(self, request: Dict) -> Optional[Dict]:
        if "spend_bundle" not in request:
            raise ValueError("Spend bundle not in request")

        spend_bundle = SpendBundle.from_json_dict(request["spend_bundle"])
        spend_name = spend_bundle.name()

        if self.service.mempool_manager.get_spendbundle(spend_name) is not None:
            status = MempoolInclusionStatus.SUCCESS
            error = None
        else:
            status, error = await self.service.respond_transaction(spend_bundle, spend_name)
            if status != MempoolInclusionStatus.SUCCESS:
                if self.service.mempool_manager.get_spendbundle(spend_name) is not None:
                    # Already in mempool
                    status = MempoolInclusionStatus.SUCCESS
                    error = None

        if status == MempoolInclusionStatus.FAILED:
            assert error is not None
            raise ValueError(f"Failed to include transaction {spend_name}, error {error.name}")
        return {
            "status": status.name,
        }

    async def is_cat_coin(self, request: Dict) -> Optional[Dict]:
        '''
        This RPC return true if the coin is a CAT coin, false otherwise

        params:
        - coin_id: the coin ID or coin name (hash of puzzle_hash + parent_hash + amount)
        '''
        coin_name: bytes32 = hexstr_to_bytes(request["coin_id"])
        coin_record = await self.service.coin_store.get_coin_record(coin_name)
        if coin_record is None:
            raise ValueError(f"Not found coin record")
        if coin_record.spent_block_index == 0:
            raise ValueError(f"Coin must be spent to have a solution: {coin_record}")

        height = coin_record.spent_block_index
        header_hash = self.service.blockchain.height_to_hash(height)
        block: Optional[FullBlock] = await self.service.block_store.get_full_block(header_hash)

        if block is None or block.transactions_generator is None:
            raise ValueError("Invalid block or block generator")

        block_generator: Optional[BlockGenerator] = await self.service.blockchain.get_block_generator(block)
        assert block_generator is not None
        error, puzzle, _ = get_puzzle_and_solution_for_coin(
            block_generator, coin_name, self.service.constants.MAX_BLOCK_COST_CLVM
        )
        if error is not None:
            raise ValueError(f"Error: {error}")

        is_cat_coin, _ = match_cat_puzzle(puzzle)
        return {"is_cat_coin": is_cat_coin}

    async def are_cat_coins(self, request: Dict) -> Optional[Dict]:
        '''
        This RPC return a list of true/false for each coin if the coin in the list are CAT coins, false otherwise

        params:
        - coin_ids: the list of unique coin IDs or coin names (hash of puzzle_hash + parent_hash + amount)
        '''
        coin_ids: List[str] = request["coin_ids"]
        coin_names: List[bytes32] = [hexstr_to_bytes(coin_id) for coin_id in coin_ids]
        if len(coin_names) != len(set(coin_names)):
            raise ValueError(f"Existing duplicated coin_names {coin_ids}")

        coin_records: List[CoinRecord] = await self.service.coin_store.get_coin_records_by_names(names=coin_names, include_spent_coins=True)
        if coin_records is None:
            raise ValueError(f"Not found coin records")

        if len(coin_records) != len(coin_names):
            raise ValueError(f"Inconsistent length between coin_names and coin_records: {len(coin_names)} != {len(coin_records)}")

        coin_records_map: Dict[bytes32, CoinRecord] = {}
        for cr in coin_records:
            coin_records_map[cr.name] = cr

        block_generator_map: Dict[int, Optional[BlockGenerator]] = {}
        async def get_block_generator(height: int) -> Optional[BlockGenerator]:
            if height in block_generator_map:
                return block_generator_map[height]

            header_hash = self.service.blockchain.height_to_hash(height)
            block: Optional[FullBlock] = await self.service.block_store.get_full_block(header_hash)

            if block is None or block.transactions_generator is None:
                raise ValueError("Invalid block or block generator")

            block_generator: Optional[BlockGenerator] = await self.service.blockchain.get_block_generator(block)
            block_generator_map[height] = block_generator
            return block_generator

        # Make sure the are_cat_list has the same order with the coin_names
        res: List[bool] = []
        for coin_name in coin_names:
            if not coin_name in coin_records_map:
                raise ValueError(f"Not found coin record")

            coin_record = coin_records_map[coin_name]
            if coin_record.spent_block_index == 0:
                raise ValueError(f"Coin must be spent to have a solution: {coin_record}")
            if coin_record.name != coin_name:
                raise ValueError(f"Inconsistent between coin name and coin_record.name(): {coin_record.name} != {coin_name}")

            height = coin_record.spent_block_index
            block_generator = await get_block_generator(height=height)
            assert block_generator is not None

            error, puzzle, _ = get_puzzle_and_solution_for_coin(
                block_generator, coin_name, self.service.constants.MAX_BLOCK_COST_CLVM
            )
            if error is not None:
                raise ValueError(f"Error: {error}")

            is_cat_coin, _ = match_cat_puzzle(puzzle)
            res.append(is_cat_coin)

        if len(coin_names) != len(res):
            raise ValueError(f"Inconsisten length between coin_names and result: {len(coin_names)} != {len(res)}")

        return {"are_cat_coins": res}

    async def get_cat_puzzle_hash(self, request: Dict) -> Optional[Dict]:
        asset_id: str = request["asset_id"] # CAT program tail hash
        xch_puzzle_hash: str = request["xch_puzzle_hash"]
        cat_puzzle_hash = get_cat_puzzle_hash(
            asset_id=asset_id,
            xch_puzzle_hash=xch_puzzle_hash,
        )
        return { "cat_puzzle_hash": cat_puzzle_hash }

    async def get_puzzle_and_solution(self, request: Dict) -> Optional[Dict]:
        coin_name: bytes32 = hexstr_to_bytes(request["coin_id"])
        height = request["height"]
        coin_record = await self.service.coin_store.get_coin_record(coin_name)
        if coin_record is None or not coin_record.spent or coin_record.spent_block_index != height:
            raise ValueError(f"Invalid height {height}. coin record {coin_record}")

        header_hash = self.service.blockchain.height_to_hash(height)
        block: Optional[FullBlock] = await self.service.block_store.get_full_block(header_hash)

        if block is None or block.transactions_generator is None:
            raise ValueError("Invalid block or block generator")

        block_generator: Optional[BlockGenerator] = await self.service.blockchain.get_block_generator(block)
        assert block_generator is not None
        error, puzzle, solution = get_puzzle_and_solution_for_coin(
            block_generator, coin_name, self.service.constants.MAX_BLOCK_COST_CLVM
        )
        if error is not None:
            raise ValueError(f"Error: {error}")

        puzzle_ser: SerializedProgram = SerializedProgram.from_program(Program.to(puzzle))
        solution_ser: SerializedProgram = SerializedProgram.from_program(Program.to(solution))
        return {"coin_solution": CoinSpend(coin_record.coin, puzzle_ser, solution_ser)}

    async def get_additions_and_removals(self, request: Dict) -> Optional[Dict]:
        if "header_hash" not in request:
            raise ValueError("No header_hash in request")
        header_hash = hexstr_to_bytes(request["header_hash"])

        block: Optional[FullBlock] = await self.service.block_store.get_full_block(header_hash)
        if block is None:
            raise ValueError(f"Block {header_hash.hex()} not found")

        async with self.service.blockchain.lock:
            if self.service.blockchain.height_to_hash(block.height) != header_hash:
                raise ValueError(f"Block at {header_hash.hex()} is no longer in the blockchain (it's in a fork)")
            additions: List[CoinRecord] = await self.service.coin_store.get_coins_added_at_height(block.height)
            removals: List[CoinRecord] = await self.service.coin_store.get_coins_removed_at_height(block.height)

        return {"additions": additions, "removals": removals}

    async def get_all_mempool_tx_ids(self, request: Dict) -> Optional[Dict]:
        ids = list(self.service.mempool_manager.mempool.spends.keys())
        return {"tx_ids": ids}

    async def get_all_mempool_items(self, request: Dict) -> Optional[Dict]:
        spends = {}
        for tx_id, item in self.service.mempool_manager.mempool.spends.items():
            spends[tx_id.hex()] = item
        return {"mempool_items": spends}

    async def get_mempool_item_by_tx_id(self, request: Dict) -> Optional[Dict]:
        if "tx_id" not in request:
            raise ValueError("No tx_id in request")
        tx_id: bytes32 = hexstr_to_bytes(request["tx_id"])

        item = self.service.mempool_manager.get_mempool_item(tx_id)
        if item is None:
            raise ValueError(f"Tx id 0x{tx_id.hex()} not in the mempool")

        return {"mempool_item": item}
