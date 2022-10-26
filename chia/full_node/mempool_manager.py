import asyncio
import collections
import logging
from concurrent.futures import Executor
from multiprocessing.context import BaseContext
import time
from concurrent.futures.process import ProcessPoolExecutor

from chia.full_node.fee_estimation import FeeMempoolInfo, FeeBlockInfo
from chia.types.clvm_cost import CLVMCost
from chia.types.fee_rate import FeeRate
from chia.util.inline_executor import InlineExecutor
from typing import Dict, List, Optional, Set, Tuple
from blspy import GTElement
from chiabip158 import PyBIP158

from chia.util import cached_bls
from chia.consensus.block_record import BlockRecord
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.coin_store import CoinStore
from chia.full_node.mempool import Mempool
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.full_node.pending_tx_cache import PendingTxCache
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.types.coin_record import CoinRecord
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.mempool_item import MempoolItem
from chia.types.spend_bundle import SpendBundle
from chia.util.cached_bls import LOCAL_CACHE
from chia.util.condition_tools import pkm_pairs
from chia.util.errors import Err, ValidationError
from chia.util.generator_tools import additions_for_npc
from chia.util.ints import uint32, uint64
from chia.util.lru_cache import LRUCache
from chia.util.setproctitle import getproctitle, setproctitle
from chia.full_node.mempool_check_conditions import mempool_check_time_locks

log = logging.getLogger(__name__)


def validate_clvm_and_signature(
    spend_bundle_bytes: bytes, max_cost: int, cost_per_byte: int, additional_data: bytes
) -> Tuple[Optional[Err], bytes, Dict[bytes32, bytes]]:
    """
    Validates CLVM and aggregate signature for a spendbundle. This is meant to be called under a ProcessPoolExecutor
    in order to validate the heavy parts of a transaction in a different thread. Returns an optional error,
    the NPCResult and a cache of the new pairings validated (if not error)
    """
    try:
        bundle: SpendBundle = SpendBundle.from_bytes(spend_bundle_bytes)
        program = simple_solution_generator(bundle)
        # npc contains names of the coins removed, puzzle_hashes and their spend conditions
        result: NPCResult = get_name_puzzle_conditions(
            program, max_cost, cost_per_byte=cost_per_byte, mempool_mode=True
        )

        if result.error is not None:
            return Err(result.error), b"", {}

        pks: List[bytes48] = []
        msgs: List[bytes] = []
        assert result.conds is not None
        pks, msgs = pkm_pairs(result.conds, additional_data)

        # Verify aggregated signature
        cache: LRUCache[bytes32, GTElement] = LRUCache(10000)
        if not cached_bls.aggregate_verify(pks, msgs, bundle.aggregated_signature, True, cache):
            return Err.BAD_AGGREGATE_SIGNATURE, b"", {}
        new_cache_entries: Dict[bytes32, bytes] = {}
        for k, v in cache.cache.items():
            new_cache_entries[k] = bytes(v)
    except ValidationError as e:
        return e.code, b"", {}
    except Exception:
        return Err.UNKNOWN, b"", {}

    return None, bytes(result), new_cache_entries


class MempoolManager:
    pool: Executor

    def __init__(
        self,
        coin_store: CoinStore,
        consensus_constants: ConsensusConstants,
        multiprocessing_context: Optional[BaseContext] = None,
        *,
        single_threaded: bool = False,
    ):
        self.constants: ConsensusConstants = consensus_constants

        # Keep track of seen spend_bundles
        self.seen_bundle_hashes: Dict[bytes32, bytes32] = {}

        self.coin_store = coin_store

        # The fee per cost must be above this amount to consider the fee "nonzero", and thus able to kick out other
        # transactions. This prevents spam. This is equivalent to 0.055 XCH per block, or about 0.00005 XCH for two
        # spends.
        self.nonzero_fee_minimum_fpc = 5

        self.limit_factor = 0.5
        self.mempool_max_total_cost = int(self.constants.MAX_BLOCK_COST_CLVM * self.constants.MEMPOOL_BLOCK_BUFFER)

        # Transactions that were unable to enter mempool, used for retry. (they were invalid)
        self.potential_cache = PendingTxCache(self.constants.MAX_BLOCK_COST_CLVM * 1)
        self.seen_cache_size = 10000
        if single_threaded:
            self.pool = InlineExecutor()
        else:
            self.pool = ProcessPoolExecutor(
                max_workers=2,
                mp_context=multiprocessing_context,
                initializer=setproctitle,
                initargs=(f"{getproctitle()}_worker",),
            )

        # The mempool will correspond to a certain peak
        self.peak: Optional[BlockRecord] = None
        self.mempool: Mempool = Mempool(
            self.mempool_max_total_cost,
            uint64(self.nonzero_fee_minimum_fpc),
            uint64(self.constants.MAX_BLOCK_COST_CLVM),
        )

    def shut_down(self) -> None:
        self.pool.shutdown(wait=True)

    async def create_bundle_from_mempool(
        self, last_tb_header_hash: bytes32
    ) -> Optional[Tuple[SpendBundle, List[Coin], List[Coin]]]:
        """
        Returns aggregated spendbundle that can be used for creating new block,
        additions and removals in that spend_bundle
        """
        if self.peak is None or self.peak.header_hash != last_tb_header_hash:
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

    def add_and_maybe_pop_seen(self, spend_name: bytes32) -> None:
        self.seen_bundle_hashes[spend_name] = spend_name
        while len(self.seen_bundle_hashes) > self.seen_cache_size:
            first_in = list(self.seen_bundle_hashes.keys())[0]
            self.seen_bundle_hashes.pop(first_in)

    def seen(self, bundle_hash: bytes32) -> bool:
        """Return true if we saw this spendbundle recently"""
        return bundle_hash in self.seen_bundle_hashes

    def remove_seen(self, bundle_hash: bytes32) -> None:
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

            # All coins spent in all conflicting items must also be spent in the new item. (superset rule). This is
            # important because otherwise there exists an attack. A user spends coin A. An attacker replaces the
            # bundle with AB with a higher fee. An attacker then replaces the bundle with just B with a higher
            # fee than AB therefore kicking out A altogether. The better way to solve this would be to keep a cache
            # of booted transactions like A, and retry them after they get removed from mempool due to a conflict.
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

    async def pre_validate_spendbundle(
        self, new_spend: SpendBundle, new_spend_bytes: Optional[bytes], spend_name: bytes32
    ) -> NPCResult:
        """
        Errors are included within the cached_result.
        This runs in another process so we don't block the main thread
        """
        start_time = time.time()
        if new_spend_bytes is None:
            new_spend_bytes = bytes(new_spend)

        err, cached_result_bytes, new_cache_entries = await asyncio.get_running_loop().run_in_executor(
            self.pool,
            validate_clvm_and_signature,
            new_spend_bytes,
            int(self.limit_factor * self.constants.MAX_BLOCK_COST_CLVM),
            self.constants.COST_PER_BYTE,
            self.constants.AGG_SIG_ME_ADDITIONAL_DATA,
        )

        if err is not None:
            raise ValidationError(err)
        for cache_entry_key, cached_entry_value in new_cache_entries.items():
            LOCAL_CACHE.put(cache_entry_key, GTElement.from_bytes_unchecked(cached_entry_value))
        ret: NPCResult = NPCResult.from_bytes(cached_result_bytes)
        end_time = time.time()
        duration = end_time - start_time
        log.log(
            logging.DEBUG if duration < 2 else logging.WARNING,
            f"pre_validate_spendbundle took {end_time - start_time:0.4f} seconds for {spend_name}",
        )
        return ret

    async def add_spend_bundle(
        self,
        new_spend: SpendBundle,
        npc_result: NPCResult,
        spend_name: bytes32,
    ) -> Tuple[Optional[uint64], MempoolInclusionStatus, Optional[Err]]:
        """
        Validates and adds to mempool a new_spend with the given NPCResult, and spend_name, and the current mempool.
        The mempool should be locked during this call (blockchain lock). If there are mempool conflicts, the conflicting
        spends might be removed (if the new spend is a superset of the previous). Otherwise, the new spend might be
        added to the potential pool.

        Args:
            new_spend: spend bundle to validate and add
            npc_result: result of running the clvm transaction in a fake block
            spend_name: hash of the spend bundle data, passed in as an optimization

        Returns:
            Optional[uint64]: cost of the entire transaction, None iff status is FAILED
            MempoolInclusionStatus:  SUCCESS (should add to pool), FAILED (cannot add), and PENDING (can add later)
            Optional[Err]: Err is set iff status is FAILED
        """

        # Skip if already added
        if spend_name in self.mempool.spends:
            cost: Optional[uint64] = self.mempool.spends[spend_name].cost
            assert cost is not None
            return uint64(cost), MempoolInclusionStatus.SUCCESS, None

        err, item, remove_items = await self.validate_spend_bundle(new_spend, npc_result, spend_name)
        if err is None:
            # No error, immediately add to mempool, after removing conflicting TXs.
            assert item is not None
            self.mempool.add_to_pool(item)
            self.mempool.remove_from_pool(remove_items)
            return item.cost, MempoolInclusionStatus.SUCCESS, None
        elif item is not None:
            # There is an error,  but we still returned a mempool item, this means we should add to the pending pool.
            self.potential_cache.add(item)
            return item.cost, MempoolInclusionStatus.PENDING, err
        else:
            # Cannot add to the mempool or pending pool.
            return None, MempoolInclusionStatus.FAILED, err

    async def validate_spend_bundle(
        self,
        new_spend: SpendBundle,
        npc_result: NPCResult,
        spend_name: bytes32,
    ) -> Tuple[Optional[Err], Optional[MempoolItem], List[bytes32]]:
        """
        Validates new_spend with the given NPCResult, and spend_name, and the current mempool. The mempool should
        be locked during this call (blockchain lock).

        Args:
            new_spend: spend bundle to validate
            npc_result: result of running the clvm transaction in a fake block
            spend_name: hash of the spend bundle data, passed in as an optimization

        Returns:
            Optional[Err]: Err is set if we cannot add to the mempool, None if we will immediately add to mempool
            Optional[MempoolItem]: the item to add (to mempool or pending pool)
            List[bytes32]: conflicting mempool items to remove, if no Err
        """
        start_time = time.time()
        if self.peak is None:
            return Err.MEMPOOL_NOT_INITIALIZED, None, []

        assert npc_result.error is None
        if npc_result.error is not None:
            return Err(npc_result.error), None, []

        cost = npc_result.cost

        log.debug(f"Cost: {cost}")

        if cost > int(self.limit_factor * self.constants.MAX_BLOCK_COST_CLVM):
            # we shouldn't ever end up here, since the cost is limited when we
            # execute the CLVM program.
            return Err.BLOCK_COST_EXCEEDS_MAX, None, []

        assert npc_result.conds is not None
        # build removal list
        removal_names: List[bytes32] = [bytes32(spend.coin_id) for spend in npc_result.conds.spends]
        if set(removal_names) != set([s.name() for s in new_spend.removals()]):
            # If you reach here it's probably because your program reveal doesn't match the coin's puzzle hash
            return Err.INVALID_SPEND_BUNDLE, None, []

        additions: List[Coin] = additions_for_npc(npc_result)

        additions_dict: Dict[bytes32, Coin] = {}
        for add in additions:
            additions_dict[add.name()] = add

        addition_amount: int = 0
        # Check additions for max coin amount
        for coin in additions:
            if coin.amount < 0:
                return Err.COIN_AMOUNT_NEGATIVE, None, []
            if coin.amount > self.constants.MAX_COIN_AMOUNT:
                return Err.COIN_AMOUNT_EXCEEDS_MAXIMUM, None, []
            addition_amount = addition_amount + coin.amount
        # Check for duplicate outputs
        addition_counter = collections.Counter(_.name() for _ in additions)
        for k, v in addition_counter.items():
            if v > 1:
                return Err.DUPLICATE_OUTPUT, None, []
        # Check for duplicate inputs
        removal_counter = collections.Counter(name for name in removal_names)
        for k, v in removal_counter.items():
            if v > 1:
                return Err.DOUBLE_SPEND, None, []

        removal_record_dict: Dict[bytes32, CoinRecord] = {}
        removal_amount: int = 0
        for name in removal_names:
            removal_record = await self.coin_store.get_coin_record(name)
            if removal_record is None and name not in additions_dict:
                return Err.UNKNOWN_UNSPENT, None, []
            elif name in additions_dict:
                removal_coin = additions_dict[name]
                # The timestamp and block-height of this coin being spent needs
                # to be consistent with what we use to check time-lock
                # conditions (below). All spends (including ephemeral coins) are
                # spent simultaneously. Ephemeral coins with an
                # ASSERT_SECONDS_RELATIVE 0 condition are still OK to spend in
                # the same block.
                assert self.peak.timestamp is not None
                removal_record = CoinRecord(
                    removal_coin,
                    uint32(self.peak.height + 1),
                    uint32(0),
                    False,
                    self.peak.timestamp,
                )

            assert removal_record is not None
            removal_amount = removal_amount + removal_record.coin.amount
            removal_record_dict[name] = removal_record

        removals: List[Coin] = [record.coin for record in removal_record_dict.values()]

        if addition_amount > removal_amount:
            return Err.MINTING_COIN, None, []

        fees = uint64(removal_amount - addition_amount)
        assert_fee_sum: uint64 = uint64(npc_result.conds.reserve_fee)

        if fees < assert_fee_sum:
            return Err.RESERVE_FEE_CONDITION_FAILED, None, []

        if cost == 0:
            return Err.UNKNOWN, None, []

        fees_per_cost: float = fees / cost
        # If pool is at capacity check the fee, if not then accept even without the fee
        if self.mempool.at_full_capacity(cost):
            if fees_per_cost < self.nonzero_fee_minimum_fpc:
                return Err.INVALID_FEE_TOO_CLOSE_TO_ZERO, None, []
            if fees_per_cost <= self.mempool.get_min_fee_rate(cost):
                return Err.INVALID_FEE_LOW_FEE, None, []
        # Check removals against UnspentDB + DiffStore + Mempool + SpendBundle
        # Use this information later when constructing a block
        fail_reason, conflicts = await self.check_removals(removal_record_dict)
        # If there is a mempool conflict check if this SpendBundle has a higher fee per cost than all others
        conflicting_pool_items: Dict[bytes32, MempoolItem] = {}

        # If we have a mempool conflict, continue, since we still want to keep around the TX in the pending pool.
        if fail_reason is not None and fail_reason is not Err.MEMPOOL_CONFLICT:
            return fail_reason, None, []

        # Verify conditions, create hash_key list for aggsig check
        for spend in npc_result.conds.spends:
            coin_record: CoinRecord = removal_record_dict[bytes32(spend.coin_id)]
            # Check that the revealed removal puzzles actually match the puzzle hash
            if spend.puzzle_hash != coin_record.coin.puzzle_hash:
                log.warning("Mempool rejecting transaction because of wrong puzzle_hash")
                log.warning(f"{spend.puzzle_hash.hex()} != {coin_record.coin.puzzle_hash.hex()}")
                return Err.WRONG_PUZZLE_HASH, None, []

        chialisp_height = (
            self.peak.prev_transaction_block_height if not self.peak.is_transaction_block else self.peak.height
        )

        assert self.peak.timestamp is not None
        tl_error: Optional[Err] = mempool_check_time_locks(
            removal_record_dict,
            npc_result.conds,
            uint32(chialisp_height),
            self.peak.timestamp,
        )

        potential = MempoolItem(
            new_spend, uint64(fees), npc_result, cost, spend_name, additions, removals, self.peak.height
        )

        if tl_error:
            if tl_error is Err.ASSERT_HEIGHT_ABSOLUTE_FAILED or tl_error is Err.ASSERT_HEIGHT_RELATIVE_FAILED:
                return tl_error, potential, []  # MempoolInclusionStatus.PENDING
            else:
                return tl_error, None, []  # MempoolInclusionStatus.FAILED

        if fail_reason is Err.MEMPOOL_CONFLICT:
            for conflicting in conflicts:
                for c_sb_id in self.mempool.removals[conflicting.name()]:
                    sb: MempoolItem = self.mempool.spends[c_sb_id]
                    conflicting_pool_items[sb.name] = sb
            log.warning(f"Conflicting pool items: {len(conflicting_pool_items)}")
            if not self.can_replace(conflicting_pool_items, removal_record_dict, fees, fees_per_cost):
                return Err.MEMPOOL_CONFLICT, potential, []

        duration = time.time() - start_time

        log.log(
            logging.DEBUG if duration < 2 else logging.WARNING,
            f"add_spendbundle {spend_name} took {duration:0.2f} seconds. "
            f"Cost: {cost} ({round(100.0 * cost/self.constants.MAX_BLOCK_COST_CLVM, 3)}% of max block cost)",
        )

        return None, potential, list(conflicting_pool_items.keys())

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
            if record.spent:
                return Err.DOUBLE_SPEND, []
            # 2. Checks if there's a mempool conflict
            if removal.name() in self.mempool.removals:
                conflicts.append(removal)

        if len(conflicts) > 0:
            return Err.MEMPOOL_CONFLICT, conflicts
        # 5. If coins can be spent return list of unspents as we see them in local storage
        return None, []

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

    async def new_peak(
        self, new_peak: Optional[BlockRecord], last_npc_result: Optional[NPCResult]
    ) -> List[Tuple[SpendBundle, NPCResult, bytes32]]:
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
        included_items = []

        use_optimization: bool = self.peak is not None and new_peak.prev_transaction_block_hash == self.peak.header_hash
        self.peak = new_peak

        if use_optimization and last_npc_result is not None:
            # We don't reinitialize a mempool, just kick removed items
            if last_npc_result.conds is not None:
                for spend in last_npc_result.conds.spends:
                    if spend.coin_id in self.mempool.removals:
                        c_ids: List[bytes32] = self.mempool.removals[bytes32(spend.coin_id)]
                        self.mempool.remove_from_pool(c_ids)
                        for c_id in c_ids:
                            self.remove_seen(c_id)
        else:
            old_pool = self.mempool

            self.mempool = Mempool(
                self.mempool_max_total_cost,
                uint64(self.nonzero_fee_minimum_fpc),
                uint64(self.constants.MAX_BLOCK_COST_CLVM),
            )
            self.seen_bundle_hashes = {}
            for item in old_pool.spends.values():
                _, result, err = await self.add_spend_bundle(item.spend_bundle, item.npc_result, item.spend_bundle_name)
                # Only add to `seen` if inclusion worked, so it can be resubmitted in case of a reorg
                if result == MempoolInclusionStatus.SUCCESS:
                    self.add_and_maybe_pop_seen(item.spend_bundle_name)
                # If the spend bundle was confirmed or conflicting (can no longer be in mempool), it won't be
                # successfully added to the new mempool.
                if result == MempoolInclusionStatus.FAILED and err == Err.DOUBLE_SPEND:
                    # Item was in mempool, but after the new block it's a double spend.
                    # Item is most likely included in the block.
                    included_items.append(item)

        potential_txs = self.potential_cache.drain()
        txs_added = []
        for item in potential_txs.values():
            cost, status, error = await self.add_spend_bundle(
                item.spend_bundle, item.npc_result, item.spend_bundle_name
            )
            if status == MempoolInclusionStatus.SUCCESS:
                txs_added.append((item.spend_bundle, item.npc_result, item.spend_bundle_name))
        log.info(
            f"Size of mempool: {len(self.mempool.spends)} spends, cost: {self.mempool.total_mempool_cost} "
            f"minimum fee rate (in FPC) to get in for 5M cost tx: {self.mempool.get_min_fee_rate(5000000)}"
        )
        self.mempool.fee_estimator.new_block(FeeBlockInfo(new_peak.height, included_items))
        return txs_added

    async def get_items_not_in_filter(self, mempool_filter: PyBIP158, limit: int = 100) -> List[MempoolItem]:
        items: List[MempoolItem] = []
        counter = 0
        broke_from_inner_loop = False

        # Send 100 with the highest fee per cost
        for dic in reversed(self.mempool.sorted_spends.values()):
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

    def get_mempool_info(self) -> FeeMempoolInfo:
        import datetime

        return FeeMempoolInfo(
            CLVMCost(uint64(self.mempool_max_total_cost)),
            FeeRate(uint64(self.nonzero_fee_minimum_fpc)),
            CLVMCost(uint64(self.mempool.total_mempool_cost)),
            datetime.datetime.now(),
            CLVMCost(uint64(self.constants.MAX_BLOCK_COST_CLVM)),
        )
