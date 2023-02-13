from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import Executor
from concurrent.futures.process import ProcessPoolExecutor
from multiprocessing.context import BaseContext
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple

from blspy import GTElement
from chiabip158 import PyBIP158

from chia.consensus.block_record import BlockRecord
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bitcoin_fee_estimator import create_bitcoin_fee_estimator
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.fee_estimation import FeeBlockInfo, MempoolInfo
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.full_node.mempool import Mempool, MempoolRemoveReason
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions, mempool_check_time_locks
from chia.full_node.pending_tx_cache import ConflictTxCache, PendingTxCache
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.types.clvm_cost import CLVMCost
from chia.types.coin_record import CoinRecord
from chia.types.fee_rate import FeeRate
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.mempool_item import MempoolItem
from chia.types.spend_bundle import SpendBundle
from chia.types.spend_bundle_conditions import SpendBundleConditions
from chia.util import cached_bls
from chia.util.cached_bls import LOCAL_CACHE
from chia.util.condition_tools import pkm_pairs
from chia.util.errors import Err, ValidationError
from chia.util.generator_tools import additions_for_npc
from chia.util.inline_executor import InlineExecutor
from chia.util.ints import uint32, uint64
from chia.util.lru_cache import LRUCache
from chia.util.setproctitle import getproctitle, setproctitle

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
        pks, msgs = pkm_pairs(result.conds, additional_data, soft_fork=True)

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


def compute_assert_height(
    removal_coin_records: Dict[bytes32, CoinRecord],
    conds: SpendBundleConditions,
) -> uint32:
    """
    Computes the most restrictive height assertion in the spend bundle. Relative
    height assertions are resolved using the confirmed heights from the coin
    records.
    """

    height: uint32 = uint32(conds.height_absolute)

    for spend in conds.spends:
        if spend.height_relative is None:
            continue
        h = uint32(removal_coin_records[bytes32(spend.coin_id)].confirmed_block_index + spend.height_relative)
        height = max(height, h)

    return height


class MempoolManager:
    pool: Executor
    constants: ConsensusConstants
    seen_bundle_hashes: Dict[bytes32, bytes32]
    get_coin_record: Callable[[bytes32], Awaitable[Optional[CoinRecord]]]
    nonzero_fee_minimum_fpc: int
    mempool_max_total_cost: int
    # a cache of MempoolItems that conflict with existing items in the pool
    _conflict_cache: ConflictTxCache
    # cache of MempoolItems with height conditions making them not valid yet
    _pending_cache: PendingTxCache
    seen_cache_size: int
    peak: Optional[BlockRecord]
    mempool: Mempool

    def __init__(
        self,
        get_coin_record: Callable[[bytes32], Awaitable[Optional[CoinRecord]]],
        consensus_constants: ConsensusConstants,
        multiprocessing_context: Optional[BaseContext] = None,
        *,
        single_threaded: bool = False,
    ):
        self.constants: ConsensusConstants = consensus_constants

        # Keep track of seen spend_bundles
        self.seen_bundle_hashes: Dict[bytes32, bytes32] = {}

        self.get_coin_record = get_coin_record

        # The fee per cost must be above this amount to consider the fee "nonzero", and thus able to kick out other
        # transactions. This prevents spam. This is equivalent to 0.055 XCH per block, or about 0.00005 XCH for two
        # spends.
        self.nonzero_fee_minimum_fpc = 5

        BLOCK_SIZE_LIMIT_FACTOR = 0.5
        self.max_block_clvm_cost = uint64(self.constants.MAX_BLOCK_COST_CLVM * BLOCK_SIZE_LIMIT_FACTOR)
        self.mempool_max_total_cost = int(self.constants.MAX_BLOCK_COST_CLVM * self.constants.MEMPOOL_BLOCK_BUFFER)

        # Transactions that were unable to enter mempool, used for retry. (they were invalid)
        self._conflict_cache = ConflictTxCache(self.constants.MAX_BLOCK_COST_CLVM * 1, 1000)
        self._pending_cache = PendingTxCache(self.constants.MAX_BLOCK_COST_CLVM * 1, 1000)
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
        self.fee_estimator: FeeEstimatorInterface = create_bitcoin_fee_estimator(self.max_block_clvm_cost)
        mempool_info = MempoolInfo(
            CLVMCost(uint64(self.mempool_max_total_cost)),
            FeeRate(uint64(self.nonzero_fee_minimum_fpc)),
            CLVMCost(uint64(self.max_block_clvm_cost)),
        )
        self.mempool: Mempool = Mempool(mempool_info, self.fee_estimator)

    def shut_down(self) -> None:
        self.pool.shutdown(wait=True)

    def process_mempool_items(
        self, item_inclusion_filter: Callable[[MempoolManager, MempoolItem], bool]
    ) -> Tuple[List[SpendBundle], uint64, List[Coin], List[Coin]]:
        cost_sum = 0  # Checks that total cost does not exceed block maximum
        fee_sum = 0  # Checks that total fees don't exceed 64 bits
        spend_bundles: List[SpendBundle] = []
        removals: List[Coin] = []
        additions: List[Coin] = []
        for dic in reversed(self.mempool.sorted_spends.values()):
            for item in dic.values():
                if not item_inclusion_filter(self, item):
                    continue
                log.info(f"Cumulative cost: {cost_sum}, fee per cost: {item.fee / item.cost}")
                if (
                    item.cost + cost_sum > self.max_block_clvm_cost
                    or item.fee + fee_sum > self.constants.MAX_COIN_AMOUNT
                ):
                    return (spend_bundles, uint64(cost_sum), additions, removals)
                spend_bundles.append(item.spend_bundle)
                cost_sum += item.cost
                fee_sum += item.fee
                removals.extend(item.removals)
                additions.extend(item.additions)
        return (spend_bundles, uint64(cost_sum), additions, removals)

    def create_bundle_from_mempool(
        self,
        last_tb_header_hash: bytes32,
        item_inclusion_filter: Optional[Callable[[MempoolManager, MempoolItem], bool]] = None,
    ) -> Optional[Tuple[SpendBundle, List[Coin], List[Coin]]]:
        """
        Returns aggregated spendbundle that can be used for creating new block,
        additions and removals in that spend_bundle
        """
        if self.peak is None or self.peak.header_hash != last_tb_header_hash:
            return None

        if item_inclusion_filter is None:

            def always(mm: MempoolManager, mi: MempoolItem) -> bool:
                return True

            item_inclusion_filter = always

        log.info(f"Starting to make block, max cost: {self.max_block_clvm_cost}")
        spend_bundles, cost_sum, additions, removals = self.process_mempool_items(item_inclusion_filter)
        if len(spend_bundles) == 0:
            return None
        log.info(
            f"Cumulative cost of block (real cost should be less) {cost_sum}. Proportion "
            f"full: {cost_sum / self.max_block_clvm_cost}"
        )
        agg = SpendBundle.aggregate(spend_bundles)
        return agg, additions, removals

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

        if new_spend.coin_spends == []:
            raise ValidationError(Err.INVALID_SPEND_BUNDLE, "Empty SpendBundle")

        err, cached_result_bytes, new_cache_entries = await asyncio.get_running_loop().run_in_executor(
            self.pool,
            validate_clvm_and_signature,
            new_spend_bytes,
            self.max_block_clvm_cost,
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
        self, new_spend: SpendBundle, npc_result: NPCResult, spend_name: bytes32, first_added_height: uint32
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

        err, item, remove_items = await self.validate_spend_bundle(
            new_spend, npc_result, spend_name, first_added_height
        )
        if err is None:
            # No error, immediately add to mempool, after removing conflicting TXs.
            assert item is not None
            self.mempool.remove_from_pool(remove_items, MempoolRemoveReason.CONFLICT)
            self.mempool.add_to_pool(item)
            return item.cost, MempoolInclusionStatus.SUCCESS, None
        elif err is Err.MEMPOOL_CONFLICT and item is not None:
            # The transaction has a conflict with another item in the
            # mempool, put it aside and re-try it later
            self._conflict_cache.add(item)
            return item.cost, MempoolInclusionStatus.PENDING, err
        elif item is not None:
            # The transasction has a height assertion and is not yet valid.
            # remember it to try it again later
            self._pending_cache.add(item)
            return item.cost, MempoolInclusionStatus.PENDING, err
        else:
            # Cannot add to the mempool or pending pool.
            return None, MempoolInclusionStatus.FAILED, err

    async def validate_spend_bundle(
        self,
        new_spend: SpendBundle,
        npc_result: NPCResult,
        spend_name: bytes32,
        first_added_height: uint32,
    ) -> Tuple[Optional[Err], Optional[MempoolItem], List[bytes32]]:
        """
        Validates new_spend with the given NPCResult, and spend_name, and the current mempool. The mempool should
        be locked during this call (blockchain lock).

        Args:
            new_spend: spend bundle to validate
            npc_result: result of running the clvm transaction in a fake block
            spend_name: hash of the spend bundle data, passed in as an optimization
            first_added_height: The block height that `new_spend`  first entered this node's mempool.
                Used to estimate how long a spend has taken to be included on the chain.
                This value could differ node to node. Not preserved across full_node restarts.

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

        assert npc_result.conds is not None
        # build removal list
        removal_names: List[bytes32] = [bytes32(spend.coin_id) for spend in npc_result.conds.spends]
        if set(removal_names) != set([s.name() for s in new_spend.removals()]):
            # If you reach here it's probably because your program reveal doesn't match the coin's puzzle hash
            return Err.INVALID_SPEND_BUNDLE, None, []

        additions: List[Coin] = additions_for_npc(npc_result)
        additions_dict: Dict[bytes32, Coin] = {}
        addition_amount: int = 0
        for add in additions:
            additions_dict[add.name()] = add
            addition_amount = addition_amount + add.amount

        removal_record_dict: Dict[bytes32, CoinRecord] = {}
        removal_amount: int = 0
        for name in removal_names:
            removal_record = await self.get_coin_record(name)
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
        fail_reason, conflicts = self.check_removals(removal_record_dict)
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

        assert_height: Optional[uint32] = None
        if tl_error:
            assert_height = compute_assert_height(removal_record_dict, npc_result.conds)

        potential = MempoolItem(
            new_spend, uint64(fees), npc_result, cost, spend_name, additions, first_added_height, assert_height
        )

        if tl_error:
            if tl_error is Err.ASSERT_HEIGHT_ABSOLUTE_FAILED or tl_error is Err.ASSERT_HEIGHT_RELATIVE_FAILED:
                return tl_error, potential, []  # MempoolInclusionStatus.PENDING
            else:
                return tl_error, None, []  # MempoolInclusionStatus.FAILED

        if fail_reason is Err.MEMPOOL_CONFLICT:
            for conflicting in conflicts:
                for c_sb_id in self.mempool.removal_coin_id_to_spendbundle_ids[conflicting.name()]:
                    sb: MempoolItem = self.mempool.spends[c_sb_id]
                    conflicting_pool_items[sb.name] = sb
            log.debug(f"Replace attempted. number of MempoolItems: {len(conflicting_pool_items)}")
            if not self.can_replace(conflicting_pool_items, removal_record_dict, fees, fees_per_cost):
                return Err.MEMPOOL_CONFLICT, potential, []

        duration = time.time() - start_time

        log.log(
            logging.DEBUG if duration < 2 else logging.WARNING,
            f"add_spendbundle {spend_name} took {duration:0.2f} seconds. "
            f"Cost: {cost} ({round(100.0 * cost/self.constants.MAX_BLOCK_COST_CLVM, 3)}% of max block cost)",
        )

        return None, potential, list(conflicting_pool_items.keys())

    def check_removals(self, removals: Dict[bytes32, CoinRecord]) -> Tuple[Optional[Err], List[Coin]]:
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
            if removal.name() in self.mempool.removal_coin_id_to_spendbundle_ids:
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

    def get_mempool_item(self, bundle_hash: bytes32, include_pending: bool = False) -> Optional[MempoolItem]:
        """
        Returns the MempoolItem in the mempool that matches the provided spend bundle hash (id)
        or None if not found.

        If include_pending is specified, also check the PENDING cache.
        """
        item = self.mempool.spends.get(bundle_hash, None)
        if not item and include_pending:
            # no async lock needed since we're not mutating the pending_cache
            item = self._pending_cache.get(bundle_hash)
        if not item and include_pending:
            item = self._conflict_cache.get(bundle_hash)

        return item

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
        self.fee_estimator.new_block_height(new_peak.height)
        included_items = []

        use_optimization: bool = self.peak is not None and new_peak.prev_transaction_block_hash == self.peak.header_hash
        self.peak = new_peak

        if use_optimization and last_npc_result is not None:
            # We don't reinitialize a mempool, just kick removed items
            if last_npc_result.conds is not None:
                for spend in last_npc_result.conds.spends:
                    if spend.coin_id in self.mempool.removal_coin_id_to_spendbundle_ids:
                        spendbundle_ids: List[bytes32] = self.mempool.removal_coin_id_to_spendbundle_ids[
                            bytes32(spend.coin_id)
                        ]
                        for spendbundle_id in spendbundle_ids:
                            item = self.mempool.spends.get(spendbundle_id)
                            if item:
                                included_items.append(item)
                            self.remove_seen(spendbundle_id)
                        self.mempool.remove_from_pool(spendbundle_ids, MempoolRemoveReason.BLOCK_INCLUSION)
        else:
            old_pool = self.mempool
            self.mempool = Mempool(old_pool.mempool_info, old_pool.fee_estimator)
            self.seen_bundle_hashes = {}
            for item in old_pool.spends.values():
                _, result, err = await self.add_spend_bundle(
                    item.spend_bundle, item.npc_result, item.spend_bundle_name, item.height_added_to_mempool
                )
                # Only add to `seen` if inclusion worked, so it can be resubmitted in case of a reorg
                if result == MempoolInclusionStatus.SUCCESS:
                    self.add_and_maybe_pop_seen(item.spend_bundle_name)
                # If the spend bundle was confirmed or conflicting (can no longer be in mempool), it won't be
                # successfully added to the new mempool.
                if result == MempoolInclusionStatus.FAILED and err == Err.DOUBLE_SPEND:
                    # Item was in mempool, but after the new block it's a double spend.
                    # Item is most likely included in the block.
                    included_items.append(item)

        potential_txs = self._pending_cache.drain(new_peak.height)
        potential_txs.update(self._conflict_cache.drain())
        txs_added = []
        for item in potential_txs.values():
            cost, status, error = await self.add_spend_bundle(
                item.spend_bundle, item.npc_result, item.spend_bundle_name, item.height_added_to_mempool
            )
            if status == MempoolInclusionStatus.SUCCESS:
                txs_added.append((item.spend_bundle, item.npc_result, item.spend_bundle_name))
        log.info(
            f"Size of mempool: {len(self.mempool.spends)} spends, "
            f"cost: {self.mempool.total_mempool_cost} "
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
