import asyncio
import collections
import dataclasses
import logging
import time
from concurrent.futures.process import ProcessPoolExecutor
from typing import Dict, List, Optional, Set, Tuple
from blspy import AugSchemeMPL, G1Element
from chiabip158 import PyBIP158

from chia.consensus.block_record import BlockRecord
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult, calculate_cost_of_program
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.coin_store import CoinStore
from chia.full_node.mempool import Mempool
from chia.full_node.mempool_check_conditions import mempool_check_conditions_dict, get_name_puzzle_conditions
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.mempool_item import MempoolItem
from chia.types.spend_bundle import SpendBundle
from chia.util.clvm import int_from_bytes
from chia.util.condition_tools import (
    pkm_pairs_for_conditions_dict,
    coin_announcements_names_for_npc,
    puzzle_announcements_names_for_npc,
)
from chia.util.errors import Err
from chia.util.generator_tools import additions_for_npc
from chia.util.ints import uint32, uint64
from chia.util.streamable import recurse_jsonify

log = logging.getLogger(__name__)


def get_npc_multiprocess(spend_bundle_bytes: bytes, max_cost: int) -> bytes:
    program = simple_solution_generator(SpendBundle.from_bytes(spend_bundle_bytes))
    # npc contains names of the coins removed, puzzle_hashes and their spend conditions
    return bytes(get_name_puzzle_conditions(program, max_cost, True))


class MempoolManager:
    def __init__(self, coin_store: CoinStore, consensus_constants: ConsensusConstants):
        self.constants: ConsensusConstants = consensus_constants
        self.constants_json = recurse_jsonify(dataclasses.asdict(self.constants))

        # Transactions that were unable to enter mempool, used for retry. (they were invalid)
        self.potential_txs: Dict[bytes32, MempoolItem] = {}
        # Keep track of seen spend_bundles
        self.seen_bundle_hashes: Dict[bytes32, bytes32] = {}

        self.coin_store = coin_store

        # The fee per cost must be above this amount to consider the fee "nonzero", and thus able to kick out other
        # transactions. This prevents spam. This is equivalent to 0.055 XCH per block, or about 0.00005 XCH for two
        # spends.
        self.nonzero_fee_minimum_fpc = 5

        self.limit_factor = 0.5
        self.mempool_max_total_cost = int(self.constants.MAX_BLOCK_COST_CLVM * self.constants.MEMPOOL_BLOCK_BUFFER)
        self.potential_cache_max_total_cost = int(self.constants.MAX_BLOCK_COST_CLVM * 5)
        self.potential_cache_cost: int = 0
        self.seen_cache_size = 10000
        self.pool = ProcessPoolExecutor(max_workers=1)

        # The mempool will correspond to a certain peak
        self.peak: Optional[BlockRecord] = None
        self.mempool: Mempool = Mempool(self.mempool_max_total_cost)

    def shut_down(self):
        self.pool.shutdown(wait=True)

    async def create_bundle_from_mempool(
        self, last_tb_header_hash: bytes32
    ) -> Optional[Tuple[SpendBundle, List[Coin], List[Coin]]]:
        """
        Returns aggregated spendbundle that can be used for creating new block,
        additions and removals in that spend_bundle
        """
        if (
            self.peak is None
            or self.peak.header_hash != last_tb_header_hash
            or int(time.time()) <= self.constants.INITIAL_FREEZE_END_TIMESTAMP
        ):
            return None

        cost_sum = 0  # Checks that total cost does not exceed block maximum
        fee_sum = 0  # Checks that total fees don't exceed 64 bits
        spend_bundles: List[SpendBundle] = []
        removals = []
        additions = []
        broke_from_inner_loop = False
        log.info(f"Starting to make block, max cost: {self.constants.MAX_BLOCK_COST_CLVM}")
        for dic in reversed(self.mempool.sorted_spends.values()):
            if broke_from_inner_loop:
                break
            for item in dic.values():
                log.info(f"Cumulative cost: {cost_sum}, fee per cost: {item.fee / item.cost}")
                if (
                    item.cost + cost_sum <= self.limit_factor * self.constants.MAX_BLOCK_COST_CLVM
                    and item.fee + fee_sum <= self.constants.MAX_COIN_AMOUNT
                ):
                    spend_bundles.append(item.spend_bundle)
                    cost_sum += item.cost
                    fee_sum += item.fee
                    removals.extend(item.removals)
                    additions.extend(item.additions)
                else:
                    broke_from_inner_loop = True
                    break
        if len(spend_bundles) > 0:
            log.info(
                f"Cumulative cost of block (real cost should be less) {cost_sum}. Proportion "
                f"full: {cost_sum / self.constants.MAX_BLOCK_COST_CLVM}"
            )
            agg = SpendBundle.aggregate(spend_bundles)
            assert set(agg.additions()) == set(additions)
            assert set(agg.removals()) == set(removals)
            return agg, additions, removals
        else:
            return None

    def get_filter(self) -> bytes:
        all_transactions: Set[bytes32] = set()
        byte_array_list = []
        for key, _ in self.mempool.spends.items():
            if key not in all_transactions:
                all_transactions.add(key)
                byte_array_list.append(bytearray(key))

        tx_filter: PyBIP158 = PyBIP158(byte_array_list)
        return bytes(tx_filter.GetEncoded())

    def is_fee_enough(self, fees: uint64, cost: uint64) -> bool:
        """
        Determines whether any of the pools can accept a transaction with a given fees
        and cost.
        """
        if cost == 0:
            return False
        fees_per_cost = fees / cost
        if not self.mempool.at_full_capacity(cost) or (
            fees_per_cost >= self.nonzero_fee_minimum_fpc and fees_per_cost > self.mempool.get_min_fee_rate(cost)
        ):
            return True
        return False

    def add_and_maybe_pop_seen(self, spend_name: bytes32):
        self.seen_bundle_hashes[spend_name] = spend_name
        while len(self.seen_bundle_hashes) > self.seen_cache_size:
            first_in = list(self.seen_bundle_hashes.keys())[0]
            self.seen_bundle_hashes.pop(first_in)

    def seen(self, bundle_hash: bytes32) -> bool:
        """Return true if we saw this spendbundle recently"""
        return bundle_hash in self.seen_bundle_hashes

    def remove_seen(self, bundle_hash: bytes32):
        if bundle_hash in self.seen_bundle_hashes:
            self.seen_bundle_hashes.pop(bundle_hash)

    @staticmethod
    def get_min_fee_increase() -> int:
        # 0.00001 XCH
        return 10000000

    def can_replace(
        self,
        conflicting_items: Dict[bytes32, MempoolItem],
        removals: Dict[bytes32, CoinRecord],
        fees: uint64,
        fees_per_cost: float,
    ) -> bool:
        conflicting_fees = 0
        conflicting_cost = 0
        for item in conflicting_items.values():
            conflicting_fees += item.fee
            conflicting_cost += item.cost

            # All coins spent in all conflicting items must also be spent in
            # the new item
            for coin in item.removals:
                if coin.name() not in removals:
                    log.debug(f"Rejecting conflicting tx as it does not spend conflicting coin {coin.name()}")
                    return False

        # New item must have higher fee per cost
        conflicting_fees_per_cost = conflicting_fees / conflicting_cost
        if fees_per_cost <= conflicting_fees_per_cost:
            log.debug(
                f"Rejecting conflicting tx due to not increasing fees per cost "
                f"({fees_per_cost} <= {conflicting_fees_per_cost})"
            )
            return False

        # New item must increase the total fee at least by a certain amount
        fee_increase = fees - conflicting_fees
        if fee_increase < self.get_min_fee_increase():
            log.debug(f"Rejecting conflicting tx due to low fee increase ({fee_increase})")
            return False

        log.info(f"Replacing conflicting tx in mempool. New tx fee: {fees}, old tx fees: {conflicting_fees}")
        return True

    async def pre_validate_spendbundle(self, new_spend: SpendBundle) -> NPCResult:
        """
        Errors are included within the cached_result.
        This runs in another process so we don't block the main thread
        """
        start_time = time.time()
        cached_result_bytes = await asyncio.get_running_loop().run_in_executor(
            self.pool, get_npc_multiprocess, bytes(new_spend), self.constants.MAX_BLOCK_COST_CLVM
        )
        end_time = time.time()
        log.info(f"It took {end_time - start_time} to pre validate transaction")
        return NPCResult.from_bytes(cached_result_bytes)

    async def add_spendbundle(
        self,
        new_spend: SpendBundle,
        npc_result: NPCResult,
        spend_name: bytes32,
        validate_signature=True,
        program: Optional[SerializedProgram] = None,
    ) -> Tuple[Optional[uint64], MempoolInclusionStatus, Optional[Err]]:
        """
        Tries to add spend bundle to the mempool
        Returns the cost (if SUCCESS), the result (MempoolInclusion status), and an optional error
        """
        start_time = time.time()
        if self.peak is None:
            return None, MempoolInclusionStatus.FAILED, Err.MEMPOOL_NOT_INITIALIZED

        npc_list = npc_result.npc_list
        if program is None:
            program = simple_solution_generator(new_spend).program
        cost = calculate_cost_of_program(program, npc_result, self.constants.COST_PER_BYTE)

        log.debug(f"Cost: {cost}")

        if cost > int(self.limit_factor * self.constants.MAX_BLOCK_COST_CLVM):
            return None, MempoolInclusionStatus.FAILED, Err.BLOCK_COST_EXCEEDS_MAX

        if npc_result.error is not None:
            return None, MempoolInclusionStatus.FAILED, Err(npc_result.error)
        # build removal list
        removal_names: List[bytes32] = [npc.coin_name for npc in npc_list]

        additions = additions_for_npc(npc_list)

        additions_dict: Dict[bytes32, Coin] = {}
        for add in additions:
            additions_dict[add.name()] = add

        addition_amount = uint64(0)
        # Check additions for max coin amount
        for coin in additions:
            if coin.amount < 0:
                return (
                    None,
                    MempoolInclusionStatus.FAILED,
                    Err.COIN_AMOUNT_NEGATIVE,
                )
            if coin.amount > self.constants.MAX_COIN_AMOUNT:
                return (
                    None,
                    MempoolInclusionStatus.FAILED,
                    Err.COIN_AMOUNT_EXCEEDS_MAXIMUM,
                )
            addition_amount = uint64(addition_amount + coin.amount)
        # Check for duplicate outputs
        addition_counter = collections.Counter(_.name() for _ in additions)
        for k, v in addition_counter.items():
            if v > 1:
                return None, MempoolInclusionStatus.FAILED, Err.DUPLICATE_OUTPUT
        # Check for duplicate inputs
        removal_counter = collections.Counter(name for name in removal_names)
        for k, v in removal_counter.items():
            if v > 1:
                return None, MempoolInclusionStatus.FAILED, Err.DOUBLE_SPEND
        # Skip if already added
        if spend_name in self.mempool.spends:
            return uint64(cost), MempoolInclusionStatus.SUCCESS, None

        removal_record_dict: Dict[bytes32, CoinRecord] = {}
        removal_coin_dict: Dict[bytes32, Coin] = {}
        unknown_unspent_error: bool = False
        removal_amount = uint64(0)
        for name in removal_names:
            removal_record = await self.coin_store.get_coin_record(name)
            if removal_record is None and name not in additions_dict:
                unknown_unspent_error = True
                break
            elif name in additions_dict:
                removal_coin = additions_dict[name]
                # TODO(straya): what timestamp to use here?
                assert self.peak.timestamp is not None
                removal_record = CoinRecord(
                    removal_coin,
                    uint32(self.peak.height + 1),  # In mempool, so will be included in next height
                    uint32(0),
                    False,
                    False,
                    uint64(self.peak.timestamp + 1),
                )

            assert removal_record is not None
            removal_amount = uint64(removal_amount + removal_record.coin.amount)
            removal_record_dict[name] = removal_record
            removal_coin_dict[name] = removal_record.coin

        removals: List[Coin] = [coin for coin in removal_coin_dict.values()]

        if unknown_unspent_error:
            return None, MempoolInclusionStatus.FAILED, Err.UNKNOWN_UNSPENT

        if addition_amount > removal_amount:
            print(addition_amount, removal_amount)
            return None, MempoolInclusionStatus.FAILED, Err.MINTING_COIN

        fees = uint64(removal_amount - addition_amount)
        assert_fee_sum: uint64 = uint64(0)

        for npc in npc_list:
            if ConditionOpcode.RESERVE_FEE in npc.condition_dict:
                fee_list: List[ConditionWithArgs] = npc.condition_dict[ConditionOpcode.RESERVE_FEE]
                for cvp in fee_list:
                    fee = int_from_bytes(cvp.vars[0])
                    if fee < 0:
                        return None, MempoolInclusionStatus.FAILED, Err.RESERVE_FEE_CONDITION_FAILED
                    assert_fee_sum = assert_fee_sum + fee
        if fees < assert_fee_sum:
            return (
                None,
                MempoolInclusionStatus.FAILED,
                Err.RESERVE_FEE_CONDITION_FAILED,
            )

        if cost == 0:
            return None, MempoolInclusionStatus.FAILED, Err.UNKNOWN

        fees_per_cost: float = fees / cost
        # If pool is at capacity check the fee, if not then accept even without the fee
        if self.mempool.at_full_capacity(cost):
            if fees_per_cost < self.nonzero_fee_minimum_fpc:
                return None, MempoolInclusionStatus.FAILED, Err.INVALID_FEE_TOO_CLOSE_TO_ZERO
            if fees_per_cost <= self.mempool.get_min_fee_rate(cost):
                return None, MempoolInclusionStatus.FAILED, Err.INVALID_FEE_LOW_FEE
        # Check removals against UnspentDB + DiffStore + Mempool + SpendBundle
        # Use this information later when constructing a block
        fail_reason, conflicts = await self.check_removals(removal_record_dict)
        # If there is a mempool conflict check if this spendbundle has a higher fee per cost than all others
        tmp_error: Optional[Err] = None
        conflicting_pool_items: Dict[bytes32, MempoolItem] = {}
        if fail_reason is Err.MEMPOOL_CONFLICT:
            for conflicting in conflicts:
                sb: MempoolItem = self.mempool.removals[conflicting.name()]
                conflicting_pool_items[sb.name] = sb
            if not self.can_replace(conflicting_pool_items, removal_record_dict, fees, fees_per_cost):
                potential = MempoolItem(
                    new_spend, uint64(fees), npc_result, cost, spend_name, additions, removals, program
                )
                self.add_to_potential_tx_set(potential)
                return (
                    uint64(cost),
                    MempoolInclusionStatus.PENDING,
                    Err.MEMPOOL_CONFLICT,
                )

        elif fail_reason:
            return None, MempoolInclusionStatus.FAILED, fail_reason

        if tmp_error:
            return None, MempoolInclusionStatus.FAILED, tmp_error

        # Verify conditions, create hash_key list for aggsig check
        pks: List[G1Element] = []
        msgs: List[bytes32] = []
        error: Optional[Err] = None
        coin_announcements_in_spend: Set[bytes32] = coin_announcements_names_for_npc(npc_list)
        puzzle_announcements_in_spend: Set[bytes32] = puzzle_announcements_names_for_npc(npc_list)
        for npc in npc_list:
            coin_record: CoinRecord = removal_record_dict[npc.coin_name]
            # Check that the revealed removal puzzles actually match the puzzle hash
            if npc.puzzle_hash != coin_record.coin.puzzle_hash:
                log.warning("Mempool rejecting transaction because of wrong puzzle_hash")
                log.warning(f"{npc.puzzle_hash} != {coin_record.coin.puzzle_hash}")
                return None, MempoolInclusionStatus.FAILED, Err.WRONG_PUZZLE_HASH

            chialisp_height = (
                self.peak.prev_transaction_block_height if not self.peak.is_transaction_block else self.peak.height
            )
            assert self.peak.timestamp is not None
            error = mempool_check_conditions_dict(
                coin_record,
                coin_announcements_in_spend,
                puzzle_announcements_in_spend,
                npc.condition_dict,
                uint32(chialisp_height),
                self.peak.timestamp,
            )

            if error:
                if error is Err.ASSERT_HEIGHT_ABSOLUTE_FAILED or error is Err.ASSERT_HEIGHT_RELATIVE_FAILED:
                    potential = MempoolItem(
                        new_spend, uint64(fees), npc_result, cost, spend_name, additions, removals, program
                    )
                    self.add_to_potential_tx_set(potential)
                    return uint64(cost), MempoolInclusionStatus.PENDING, error
                break

            if validate_signature:
                for pk, message in pkm_pairs_for_conditions_dict(
                    npc.condition_dict, npc.coin_name, self.constants.AGG_SIG_ME_ADDITIONAL_DATA
                ):
                    pks.append(pk)
                    msgs.append(message)
        if error:
            return None, MempoolInclusionStatus.FAILED, error

        if validate_signature:
            # Verify aggregated signature
            if not AugSchemeMPL.aggregate_verify(pks, msgs, new_spend.aggregated_signature):
                log.warning(f"Aggsig validation error {pks} {msgs} {new_spend}")
                return None, MempoolInclusionStatus.FAILED, Err.BAD_AGGREGATE_SIGNATURE
        # Remove all conflicting Coins and SpendBundles
        if fail_reason:
            mempool_item: MempoolItem
            for mempool_item in conflicting_pool_items.values():
                self.mempool.remove_from_pool(mempool_item)

        new_item = MempoolItem(new_spend, uint64(fees), npc_result, cost, spend_name, additions, removals, program)
        self.mempool.add_to_pool(new_item, additions, removal_coin_dict)
        log.info(f"add_spendbundle took {time.time() - start_time} seconds")
        return uint64(cost), MempoolInclusionStatus.SUCCESS, None

    async def check_removals(self, removals: Dict[bytes32, CoinRecord]) -> Tuple[Optional[Err], List[Coin]]:
        """
        This function checks for double spends, unknown spends and conflicting transactions in mempool.
        Returns Error (if any), dictionary of Unspents, list of coins with conflict errors (if any any).
        Note that additions are not checked for duplicates, because having duplicate additions requires also
        having duplicate removals.
        """
        assert self.peak is not None
        conflicts: List[Coin] = []

        for record in removals.values():
            removal = record.coin
            # 1. Checks if it's been spent already
            if record.spent == 1:
                return Err.DOUBLE_SPEND, []
            # 2. Checks if there's a mempool conflict
            if removal.name() in self.mempool.removals:
                conflicts.append(removal)

        if len(conflicts) > 0:
            return Err.MEMPOOL_CONFLICT, conflicts
        # 5. If coins can be spent return list of unspents as we see them in local storage
        return None, []

    def add_to_potential_tx_set(self, item: MempoolItem):
        """
        Adds SpendBundles that have failed to be added to the pool in potential tx set.
        This is later used to retry to add them.
        """
        if item.spend_bundle_name in self.potential_txs:
            return

        self.potential_txs[item.spend_bundle_name] = item
        self.potential_cache_cost += item.cost

        while self.potential_cache_cost > self.potential_cache_max_total_cost:
            first_in = list(self.potential_txs.keys())[0]
            self.potential_cache_max_total_cost -= self.potential_txs[first_in].cost
            self.potential_txs.pop(first_in)

    def get_spendbundle(self, bundle_hash: bytes32) -> Optional[SpendBundle]:
        """Returns a full SpendBundle if it's inside one the mempools"""
        if bundle_hash in self.mempool.spends:
            return self.mempool.spends[bundle_hash].spend_bundle
        return None

    def get_mempool_item(self, bundle_hash: bytes32) -> Optional[MempoolItem]:
        """Returns a MempoolItem if it's inside one the mempools"""
        if bundle_hash in self.mempool.spends:
            return self.mempool.spends[bundle_hash]
        return None

    async def new_peak(self, new_peak: Optional[BlockRecord]) -> List[Tuple[SpendBundle, NPCResult, bytes32]]:
        """
        Called when a new peak is available, we try to recreate a mempool for the new tip.
        """
        if new_peak is None:
            return []
        if new_peak.is_transaction_block is False:
            return []
        if self.peak == new_peak:
            return []
        assert new_peak.timestamp is not None
        if new_peak.timestamp <= self.constants.INITIAL_FREEZE_END_TIMESTAMP:
            return []

        self.peak = new_peak

        old_pool = self.mempool
        self.mempool = Mempool(self.mempool_max_total_cost)

        for item in old_pool.spends.values():
            _, result, _ = await self.add_spendbundle(
                item.spend_bundle, item.npc_result, item.spend_bundle_name, False, item.program
            )
            # If the spend bundle was confirmed or conflicting (can no longer be in mempool), it won't be successfully
            # added to the new mempool. In this case, remove it from seen, so in the case of a reorg, it can be
            # resubmitted
            if result != MempoolInclusionStatus.SUCCESS:
                self.remove_seen(item.spend_bundle_name)

        potential_txs_copy = self.potential_txs.copy()
        self.potential_txs = {}
        txs_added = []
        for item in potential_txs_copy.values():
            cost, status, error = await self.add_spendbundle(
                item.spend_bundle, item.npc_result, item.spend_bundle_name, program=item.program
            )
            if status == MempoolInclusionStatus.SUCCESS:
                txs_added.append((item.spend_bundle, item.npc_result, item.spend_bundle_name))
        log.debug(
            f"Size of mempool: {len(self.mempool.spends)} spends, cost: {self.mempool.total_mempool_cost} "
            f"minimum fee to get in: {self.mempool.get_min_fee_rate(100000)}"
        )
        return txs_added

    async def get_items_not_in_filter(self, mempool_filter: PyBIP158, limit: int = 100) -> List[MempoolItem]:
        items: List[MempoolItem] = []
        counter = 0
        broke_from_inner_loop = False

        # Send 100 with highest fee per cost
        for dic in self.mempool.sorted_spends.values():
            if broke_from_inner_loop:
                break
            for item in dic.values():
                if counter == limit:
                    broke_from_inner_loop = True
                    break
                if mempool_filter.Match(bytearray(item.spend_bundle_name)):
                    continue
                items.append(item)
                counter += 1

        return items
