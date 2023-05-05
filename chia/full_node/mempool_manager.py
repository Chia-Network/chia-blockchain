from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import Executor
from concurrent.futures.process import ProcessPoolExecutor
from dataclasses import dataclass
from multiprocessing.context import BaseContext
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple, TypeVar

from blspy import GTElement
from chiabip158 import PyBIP158

from chia.consensus.block_record import BlockRecordProtocol
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bitcoin_fee_estimator import create_bitcoin_fee_estimator
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.fee_estimation import FeeBlockInfo, MempoolInfo, MempoolItemInfo
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.full_node.mempool import MEMPOOL_ITEM_FEE_LIMIT, Mempool, MempoolRemoveReason
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
from chia.util.db_wrapper import SQLITE_INT_MAX
from chia.util.errors import Err, ValidationError
from chia.util.inline_executor import InlineExecutor
from chia.util.ints import uint32, uint64
from chia.util.lru_cache import LRUCache
from chia.util.setproctitle import getproctitle, setproctitle

log = logging.getLogger(__name__)

# mempool items replacing existing ones must increase the total fee at least by
# this amount. 0.00001 XCH
MEMPOOL_MIN_FEE_INCREASE = uint64(10000000)


# TODO: once the 1.8.0 soft-fork has activated, we don't really need to pass
# the constants through here
def validate_clvm_and_signature(
    spend_bundle_bytes: bytes, max_cost: int, constants: ConsensusConstants, height: uint32
) -> Tuple[Optional[Err], bytes, Dict[bytes32, bytes]]:
    """
    Validates CLVM and aggregate signature for a spendbundle. This is meant to be called under a ProcessPoolExecutor
    in order to validate the heavy parts of a transaction in a different thread. Returns an optional error,
    the NPCResult and a cache of the new pairings validated (if not error)
    """

    additional_data = constants.AGG_SIG_ME_ADDITIONAL_DATA

    try:
        bundle: SpendBundle = SpendBundle.from_bytes(spend_bundle_bytes)
        program = simple_solution_generator(bundle)
        # npc contains names of the coins removed, puzzle_hashes and their spend conditions
        result: NPCResult = get_name_puzzle_conditions(
            program, max_cost, mempool_mode=True, constants=constants, height=height
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


@dataclass
class TimelockConditions:
    assert_height: uint32 = uint32(0)
    assert_before_height: Optional[uint32] = None
    assert_before_seconds: Optional[uint64] = None


def compute_assert_height(
    removal_coin_records: Dict[bytes32, CoinRecord],
    conds: SpendBundleConditions,
) -> TimelockConditions:
    """
    Computes the most restrictive height- and seconds assertion in the spend bundle.
    Relative heights and times are resolved using the confirmed heights and
    timestamps from the coin records.
    """

    ret = TimelockConditions()
    ret.assert_height = uint32(conds.height_absolute)
    ret.assert_before_height = (
        uint32(conds.before_height_absolute) if conds.before_height_absolute is not None else None
    )
    ret.assert_before_seconds = (
        uint64(conds.before_seconds_absolute) if conds.before_seconds_absolute is not None else None
    )

    for spend in conds.spends:
        if spend.height_relative is not None:
            h = uint32(removal_coin_records[bytes32(spend.coin_id)].confirmed_block_index + spend.height_relative)
            ret.assert_height = max(ret.assert_height, h)

        if spend.before_height_relative is not None:
            h = uint32(
                removal_coin_records[bytes32(spend.coin_id)].confirmed_block_index + spend.before_height_relative
            )
            if ret.assert_before_height is not None:
                ret.assert_before_height = min(ret.assert_before_height, h)
            else:
                ret.assert_before_height = h

        if spend.before_seconds_relative is not None:
            s = uint64(removal_coin_records[bytes32(spend.coin_id)].timestamp + spend.before_seconds_relative)
            if ret.assert_before_seconds is not None:
                ret.assert_before_seconds = min(ret.assert_before_seconds, s)
            else:
                ret.assert_before_seconds = s

    return ret


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
    peak: Optional[BlockRecordProtocol]
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
        self.peak: Optional[BlockRecordProtocol] = None
        self.fee_estimator: FeeEstimatorInterface = create_bitcoin_fee_estimator(self.max_block_clvm_cost)
        mempool_info = MempoolInfo(
            CLVMCost(uint64(self.mempool_max_total_cost)),
            FeeRate(uint64(self.nonzero_fee_minimum_fpc)),
            CLVMCost(uint64(self.max_block_clvm_cost)),
        )
        self.mempool: Mempool = Mempool(mempool_info, self.fee_estimator)

    def shut_down(self) -> None:
        self.pool.shutdown(wait=True)

    def create_bundle_from_mempool(
        self, last_tb_header_hash: bytes32, item_inclusion_filter: Optional[Callable[[bytes32], bool]] = None
    ) -> Optional[Tuple[SpendBundle, List[Coin]]]:
        """
        Returns aggregated spendbundle that can be used for creating new block,
        additions and removals in that spend_bundle
        """
        if self.peak is None or self.peak.header_hash != last_tb_header_hash:
            return None
        if item_inclusion_filter is None:

            def always(bundle_name: bytes32) -> bool:
                return True

            item_inclusion_filter = always
        return self.mempool.create_bundle_from_mempool_items(item_inclusion_filter)

    def get_filter(self) -> bytes:
        all_transactions: Set[bytes32] = set()
        byte_array_list = []
        for key in self.mempool.all_item_ids():
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

        assert self.peak is not None

        err, cached_result_bytes, new_cache_entries = await asyncio.get_running_loop().run_in_executor(
            self.pool,
            validate_clvm_and_signature,
            new_spend_bytes,
            self.max_block_clvm_cost,
            self.constants,
            self.peak.height,
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
        existing_item = self.mempool.get_item_by_id(spend_name)
        if existing_item is not None:
            return existing_item.cost, MempoolInclusionStatus.SUCCESS, None

        err, item, remove_items = await self.validate_spend_bundle(
            new_spend, npc_result, spend_name, first_added_height
        )
        if err is None:
            # No error, immediately add to mempool, after removing conflicting TXs.
            assert item is not None
            self.mempool.remove_from_pool(remove_items, MempoolRemoveReason.CONFLICT)
            err = self.mempool.add_to_pool(item)
            if err is not None:
                return item.cost, MempoolInclusionStatus.FAILED, err
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
        removal_names: Set[bytes32] = set()
        additions_dict: Dict[bytes32, Coin] = {}
        addition_amount: int = 0
        for spend in npc_result.conds.spends:
            coin_id = bytes32(spend.coin_id)
            removal_names.add(coin_id)
            for puzzle_hash, amount, _ in spend.create_coin:
                child_coin = Coin(coin_id, puzzle_hash, amount)
                additions_dict[child_coin.name()] = child_coin
                addition_amount = addition_amount + child_coin.amount

        if removal_names != set(coin_spend.coin.name() for coin_spend in new_spend.coin_spends):
            # If you reach here it's probably because your program reveal doesn't match the coin's puzzle hash
            return Err.INVALID_SPEND_BUNDLE, None, []

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

        fees = uint64(removal_amount - addition_amount)

        if cost == 0:
            return Err.UNKNOWN, None, []

        if cost > self.max_block_clvm_cost:
            return Err.BLOCK_COST_EXCEEDS_MAX, None, []

        # this is not very likely to happen, but it's here to ensure SQLite
        # never runs out of precision in its computation of fees.
        # sqlite's integers are signed int64, so the max value they can
        # represent is 2^63-1
        if fees > MEMPOOL_ITEM_FEE_LIMIT or SQLITE_INT_MAX - self.mempool.total_mempool_fees() <= fees:
            return Err.INVALID_BLOCK_FEE_AMOUNT, None, []

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

        # the height and time we pass in here represent the previous transaction
        # block's height and timestamp. In the mempool, the most recent peak
        # block we've received will be the previous transaction block, from the
        # point-of-view of the next block to be farmed. Therefore we pass in the
        # current peak's height and timestamp
        assert self.peak.timestamp is not None
        tl_error: Optional[Err] = mempool_check_time_locks(
            removal_record_dict,
            npc_result.conds,
            self.peak.height,
            self.peak.timestamp,
        )

        timelocks: TimelockConditions = compute_assert_height(removal_record_dict, npc_result.conds)

        potential = MempoolItem(
            new_spend,
            uint64(fees),
            npc_result,
            spend_name,
            first_added_height,
            timelocks.assert_height,
            timelocks.assert_before_height,
            timelocks.assert_before_seconds,
        )

        if tl_error:
            if tl_error is Err.ASSERT_HEIGHT_ABSOLUTE_FAILED or tl_error is Err.ASSERT_HEIGHT_RELATIVE_FAILED:
                return tl_error, potential, []  # MempoolInclusionStatus.PENDING
            else:
                return tl_error, None, []  # MempoolInclusionStatus.FAILED

        if fail_reason is Err.MEMPOOL_CONFLICT:
            log.debug(f"Replace attempted. number of MempoolItems: {len(conflicts)}")
            if not can_replace(conflicts, removal_names, potential):
                return Err.MEMPOOL_CONFLICT, potential, []

        duration = time.time() - start_time

        log.log(
            logging.DEBUG if duration < 2 else logging.WARNING,
            f"add_spendbundle {spend_name} took {duration:0.2f} seconds. "
            f"Cost: {cost} ({round(100.0 * cost/self.constants.MAX_BLOCK_COST_CLVM, 3)}% of max block cost)",
        )

        return None, potential, [item.name for item in conflicts]

    def check_removals(self, removals: Dict[bytes32, CoinRecord]) -> Tuple[Optional[Err], List[MempoolItem]]:
        """
        This function checks for double spends, unknown spends and conflicting transactions in mempool.
        Returns Error (if any), the set of existing MempoolItems with conflicting spends (if any).
        Note that additions are not checked for duplicates, because having duplicate additions requires also
        having duplicate removals.
        """
        assert self.peak is not None
        removals_ids = []
        for record in removals.values():
            removal = record.coin
            # 1. Checks if it's been spent already
            if record.spent:
                return Err.DOUBLE_SPEND, []
            removals_ids.append(removal.name())
        # 2. Checks if there are mempool conflicts
        conflicts = self.mempool.get_items_by_coin_ids(removals_ids)
        if len(conflicts) > 0:
            return Err.MEMPOOL_CONFLICT, conflicts
        # 5. If coins can be spent return list of unspents as we see them in local storage
        return None, []

    def get_spendbundle(self, bundle_hash: bytes32) -> Optional[SpendBundle]:
        """Returns a full SpendBundle if it's inside one the mempools"""
        item: Optional[MempoolItem] = self.mempool.get_item_by_id(bundle_hash)
        if item is not None:
            return item.spend_bundle
        return None

    def get_mempool_item(self, bundle_hash: bytes32, include_pending: bool = False) -> Optional[MempoolItem]:
        """
        Returns the MempoolItem in the mempool that matches the provided spend bundle hash (id)
        or None if not found.

        If include_pending is specified, also check the PENDING cache.
        """
        item = self.mempool.get_item_by_id(bundle_hash)
        if not item and include_pending:
            # no async lock needed since we're not mutating the pending_cache
            item = self._pending_cache.get(bundle_hash)
        if not item and include_pending:
            item = self._conflict_cache.get(bundle_hash)

        return item

    async def new_peak(
        self, new_peak: Optional[BlockRecordProtocol], last_npc_result: Optional[NPCResult]
    ) -> List[Tuple[SpendBundle, NPCResult, bytes32]]:
        """
        Called when a new peak is available, we try to recreate a mempool for the new tip.
        """
        if new_peak is None:
            return []
        # we're only interested in transaction blocks
        if new_peak.is_transaction_block is False:
            return []
        if self.peak == new_peak:
            return []
        assert new_peak.timestamp is not None
        self.fee_estimator.new_block_height(new_peak.height)
        included_items: List[MempoolItemInfo] = []

        self.mempool.new_tx_block(new_peak.height, new_peak.timestamp)

        use_optimization: bool = self.peak is not None and new_peak.prev_transaction_block_hash == self.peak.header_hash
        self.peak = new_peak

        if use_optimization and last_npc_result is not None:
            # We don't reinitialize a mempool, just kick removed items
            if last_npc_result.conds is not None:
                # transactions in the mempool may be spending multiple coins,
                # when looking up transactions by all coin IDs, we're likely to
                # find the same transaction multiple times. We put them in a set
                # to deduplicate
                spendbundle_ids_to_remove: Set[bytes32] = set()
                for spend in last_npc_result.conds.spends:
                    items: List[MempoolItem] = self.mempool.get_items_by_coin_id(bytes32(spend.coin_id))
                    for item in items:
                        included_items.append(MempoolItemInfo(item.cost, item.fee, item.height_added_to_mempool))
                        self.remove_seen(item.name)
                        spendbundle_ids_to_remove.add(item.name)
                self.mempool.remove_from_pool(list(spendbundle_ids_to_remove), MempoolRemoveReason.BLOCK_INCLUSION)
        else:
            old_pool = self.mempool
            self.mempool = Mempool(old_pool.mempool_info, old_pool.fee_estimator)
            self.seen_bundle_hashes = {}
            for item in old_pool.all_items():
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
                    included_items.append(MempoolItemInfo(item.cost, item.fee, item.height_added_to_mempool))

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
            f"Size of mempool: {self.mempool.size()} spends, "
            f"cost: {self.mempool.total_mempool_cost()} "
            f"minimum fee rate (in FPC) to get in for 5M cost tx: {self.mempool.get_min_fee_rate(5000000)}"
        )
        self.mempool.fee_estimator.new_block(FeeBlockInfo(new_peak.height, included_items))
        return txs_added

    def get_items_not_in_filter(self, mempool_filter: PyBIP158, limit: int = 100) -> List[SpendBundle]:
        items: List[SpendBundle] = []

        assert limit > 0

        # Send 100 with the highest fee per cost
        for item in self.mempool.items_by_feerate():
            if len(items) >= limit:
                return items
            if mempool_filter.Match(bytearray(item.spend_bundle_name)):
                continue
            items.append(item.spend_bundle)

        return items


T = TypeVar("T", uint32, uint64)


def optional_min(a: Optional[T], b: Optional[T]) -> Optional[T]:
    return min((v for v in [a, b] if v is not None), default=None)


def optional_max(a: Optional[T], b: Optional[T]) -> Optional[T]:
    return max((v for v in [a, b] if v is not None), default=None)


def can_replace(
    conflicting_items: List[MempoolItem],
    removal_names: Set[bytes32],
    new_item: MempoolItem,
) -> bool:
    """
    This function implements the mempool replacement rules. Given a Mempool item
    we're attempting to insert into the mempool (new_item) and the set of existing
    mempool items that conflict with it, this function answers the question whether
    the existing items can be replaced by the new one. The removals parameter are
    the coin IDs the new mempool item is spending.
    """

    conflicting_fees = 0
    conflicting_cost = 0
    assert_height: Optional[uint32] = None
    assert_before_height: Optional[uint32] = None
    assert_before_seconds: Optional[uint64] = None
    for item in conflicting_items:
        conflicting_fees += item.fee
        conflicting_cost += item.cost

        # All coins spent in all conflicting items must also be spent in the new item. (superset rule). This is
        # important because otherwise there exists an attack. A user spends coin A. An attacker replaces the
        # bundle with AB with a higher fee. An attacker then replaces the bundle with just B with a higher
        # fee than AB therefore kicking out A altogether. The better way to solve this would be to keep a cache
        # of booted transactions like A, and retry them after they get removed from mempool due to a conflict.
        for coin in item.removals:
            if coin.name() not in removal_names:
                log.debug(f"Rejecting conflicting tx as it does not spend conflicting coin {coin.name()}")
                return False

        assert_height = optional_max(assert_height, item.assert_height)
        assert_before_height = optional_min(assert_before_height, item.assert_before_height)
        assert_before_seconds = optional_min(assert_before_seconds, item.assert_before_seconds)

    # New item must have higher fee per cost
    conflicting_fees_per_cost = conflicting_fees / conflicting_cost
    if new_item.fee_per_cost <= conflicting_fees_per_cost:
        log.debug(
            f"Rejecting conflicting tx due to not increasing fees per cost "
            f"({new_item.fee_per_cost} <= {conflicting_fees_per_cost})"
        )
        return False

    # New item must increase the total fee at least by a certain amount
    fee_increase = new_item.fee - conflicting_fees
    if fee_increase < MEMPOOL_MIN_FEE_INCREASE:
        log.debug(f"Rejecting conflicting tx due to low fee increase ({fee_increase})")
        return False

    # New item may not have a different effective height/time lock (time-lock rule)
    if new_item.assert_height != assert_height:
        log.debug(
            "Rejecting conflicting tx due to changing ASSERT_HEIGHT constraints %s -> %s",
            assert_height,
            new_item.assert_height,
        )
        return False

    if new_item.assert_before_height != assert_before_height:
        log.debug(
            "Rejecting conflicting tx due to changing ASSERT_BEFORE_HEIGHT constraints %s -> %s",
            assert_before_height,
            new_item.assert_before_height,
        )
        return False

    if new_item.assert_before_seconds != assert_before_seconds:
        log.debug(
            "Rejecting conflicting tx due to changing ASSERT_BEFORE_SECONDS constraints %s -> %s",
            assert_before_seconds,
            new_item.assert_before_seconds,
        )
        return False

    log.info(f"Replacing conflicting tx in mempool. New tx fee: {new_item.fee}, old tx fees: {conflicting_fees}")
    return True
