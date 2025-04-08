from __future__ import annotations

import logging
from collections.abc import Awaitable, Iterator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from itertools import chain
from time import monotonic
from typing import Callable, Optional

from chia_rs import (
    DONT_VALIDATE_SIGNATURE,
    MEMPOOL_MODE,
    AugSchemeMPL,
    BlockBuilder,
    Coin,
    ConsensusConstants,
    G2Element,
    get_flags_for_height_and_constants,
    run_block_generator2,
    solution_generator_backrefs,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.fee_estimation import FeeMempoolInfo, MempoolInfo, MempoolItemInfo
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.clvm_cost import CLVMCost
from chia.types.coin_spend import CoinSpend
from chia.types.eligible_coin_spends import EligibleCoinSpends, SkipDedup, UnspentLineageInfo
from chia.types.generator_types import NewBlockGenerator
from chia.types.mempool_item import MempoolItem
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err

log = logging.getLogger(__name__)

# Maximum number of mempool items that can be skipped (not considered) during
# the creation of a block bundle. An item is skipped if it won't fit in the
# block we're trying to create.
MAX_SKIPPED_ITEMS = 10

# Threshold after which we stop including mempool items with fast-forward or
# dedup spends during the creation of a block generator. We do that to avoid
# spending too much time on potentially expensive items.
PRIORITY_TX_THRESHOLD = 3

# Typical cost of a standard XCH spend. It's used as a heuristic to help
# determine how close to the block size limit we're willing to go.
MIN_COST_THRESHOLD = 6_000_000

# We impose a limit on the fee a single transaction can pay in order to have the
# sum of all fees in the mempool be less than 2^63. That's the limit of sqlite's
# integers, which we rely on for computing fee per cost as well as the fee sum
MEMPOOL_ITEM_FEE_LIMIT = 2**50


@dataclass
class MempoolRemoveInfo:
    items: list[MempoolItem]
    reason: MempoolRemoveReason


@dataclass
class MempoolAddInfo:
    removals: list[MempoolRemoveInfo]
    error: Optional[Err]


class MempoolRemoveReason(Enum):
    CONFLICT = 1
    BLOCK_INCLUSION = 2
    POOL_FULL = 3
    EXPIRED = 4


class MempoolMap:
    _items: list[Optional[MempoolItem]]
    _unused_items: list[int]
    _transaction_ids: dict[bytes32, int]
    _fee_per_cost: dict[tuple[float, int], None]
    _assert_before_seconds: dict[tuple[uint64, int], None]
    _assert_before_height: dict[tuple[uint32, int], None]
    _spent_coin_ids: dict[bytes32, dict[int, None]]
    _total_fee: int
    _total_cost: int

    def __init__(self) -> None:
        self._items = []
        self._unused_items = []
        self._transaction_ids = {}
        self._fee_per_cost = {}
        self._assert_before_seconds = {}
        self._assert_before_height = {}
        self._spent_coin_ids = {}
        self._total_fee = 0
        self._total_cost = 0

    def __len__(self) -> int:
        return len(self._items) - len(self._unused_items)

    def total_fee(self) -> int:
        return self._total_fee

    def total_cost(self) -> int:
        return self._total_cost

    def add(self, item: MempoolItem) -> bool:
        if item.spend_bundle_name in self._transaction_ids:
            return False

        index = self._free_index()

        self._items[index] = item
        self._transaction_ids[item.spend_bundle_name] = index
        self._fee_per_cost[item.fee_per_cost, index] = None
        if item.assert_before_seconds is not None:
            self._assert_before_seconds[item.assert_before_seconds, index] = None
        if item.assert_before_height is not None:
            self._assert_before_height[item.assert_before_height, index] = None
        self._total_fee += item.fee
        self._total_cost += item.cost

        for coin_id, bcs in item.bundle_coin_spends.items():
            if bcs.latest_singleton_coin is not None:
                coin_id = bcs.latest_singleton_coin

            self._spent_coin_ids.setdefault(coin_id, dict())[index] = None

        return True

    def remove(self, transaction_id: bytes32) -> MempoolItem:
        index = self._transaction_ids[transaction_id]
        item = self._items[index]
        assert item is not None

        self._items[index] = None
        self._transaction_ids.pop(transaction_id)
        self._fee_per_cost.pop((item.fee_per_cost, index))
        if item.assert_before_seconds is not None:
            self._assert_before_seconds.pop((item.assert_before_seconds, index))
        if item.assert_before_height is not None:
            self._assert_before_height.pop((item.assert_before_height, index))
        self._unused_items.append(index)
        self._total_fee -= item.fee
        self._total_cost -= item.cost

        for coin_id, bcs in item.bundle_coin_spends.items():
            if bcs.latest_singleton_coin is not None:
                coin_id = bcs.latest_singleton_coin

            transaction_ids = self._spent_coin_ids.get(coin_id)

            if transaction_ids is not None:
                transaction_ids.pop(index)

        return item

    def has(self, transaction_id: bytes32) -> bool:
        return transaction_id in self._transaction_ids

    def get(self, transaction_id: bytes32) -> Optional[MempoolItem]:
        index = self._transaction_ids.get(transaction_id)

        if index is None:
            return None

        return self._items[index]

    def update_coin_index(self, transaction_id: bytes32, coin_id: bytes32, new_coin_id: bytes32) -> None:
        index = self._transaction_ids.get(transaction_id)

        if index is None:
            return

        indices = self._spent_coin_ids.get(coin_id)

        if indices is None:
            return

        if index not in indices:
            return

        indices.pop(index)

        self._spent_coin_ids.setdefault(new_coin_id, dict())[index] = None

    def items(self) -> Iterator[MempoolItem]:
        for item in self._items:
            if item is not None:
                yield item

    def low_fee_items(self) -> Iterator[MempoolItem]:
        for _, index in self._fee_per_cost.keys():
            item = self._items[index]

            if item is not None:
                yield item

    def high_fee_items(self) -> Iterator[MempoolItem]:
        for _, index in reversed(self._fee_per_cost.keys()):
            item = self._items[index]

            if item is not None:
                yield item

    def expiring_soon_seconds_items(self, max_seconds: uint64) -> Iterator[MempoolItem]:
        for seconds, index in self._assert_before_seconds.keys():
            if seconds > max_seconds:
                continue

            item = self._items[index]

            if item is not None:
                yield item

    def expiring_soon_height_items(self, max_height: uint32) -> Iterator[MempoolItem]:
        for height, index in self._assert_before_height.keys():
            if height > max_height:
                continue

            item = self._items[index]

            if item is not None:
                yield item

    def items_by_coin_ids(self, coin_ids: list[bytes32]) -> Iterator[MempoolItem]:
        all_indices: dict[int, None] = dict()

        for coin_id in coin_ids:
            indices = self._spent_coin_ids.get(coin_id)

            if indices is not None:
                all_indices.update(indices)

        for index in all_indices:
            item = self._items[index]

            if item is not None:
                yield item

    def all_coin_ids(self) -> Iterator[bytes32]:
        yield from self._spent_coin_ids.keys()

    def _free_index(self) -> int:
        if len(self._unused_items) > 0:
            return self._unused_items.pop()

        self._items.append(None)

        return len(self._items) - 1


class Mempool:
    _map: MempoolMap

    # the most recent block height and timestamp that we know of
    _block_height: uint32
    _timestamp: uint64

    def __init__(self, mempool_info: MempoolInfo, fee_estimator: FeeEstimatorInterface):
        self._map = MempoolMap()

        self._block_height = uint32(0)
        self._timestamp = uint64(0)

        self.mempool_info: MempoolInfo = mempool_info
        self.fee_estimator: FeeEstimatorInterface = fee_estimator

    def total_mempool_fees(self) -> int:
        return self._map.total_fee()

    def total_mempool_cost(self) -> CLVMCost:
        return CLVMCost(uint64(self._map.total_cost()))

    def all_items(self) -> Iterator[MempoolItem]:
        return self._map.items()

    def all_item_ids(self) -> list[bytes32]:
        return [item.spend_bundle_name for item in self._map.items()]

    def items_with_coin_ids(self, coin_ids: set[bytes32]) -> list[bytes32]:
        """
        Returns a list of transaction ids that spend or create any coins with the provided coin ids.
        This iterates over the internal items instead of using a query.
        """

        transaction_ids: list[bytes32] = []

        for item in self.all_items():
            conds = item.conds
            assert conds is not None

            for spend in conds.spends:
                if spend.coin_id in coin_ids:
                    transaction_ids.append(item.spend_bundle_name)
                    break

                for puzzle_hash, amount, _memo in spend.create_coin:
                    if Coin(spend.coin_id, puzzle_hash, uint64(amount)).name() in coin_ids:
                        transaction_ids.append(item.spend_bundle_name)
                        break
                else:
                    continue

                break

        return transaction_ids

    def items_with_puzzle_hashes(self, puzzle_hashes: set[bytes32], include_hints: bool) -> list[bytes32]:
        """
        Returns a list of transaction ids that spend or create any coins
        with the provided puzzle hashes (or hints, if enabled).
        This iterates over the internal items instead of using a query.
        """

        transaction_ids: list[bytes32] = []

        for item in self.all_items():
            conds = item.conds
            assert conds is not None

            for spend in conds.spends:
                if spend.puzzle_hash in puzzle_hashes:
                    transaction_ids.append(item.spend_bundle_name)
                    break

                for puzzle_hash, _amount, memo in spend.create_coin:
                    if puzzle_hash in puzzle_hashes or (include_hints and memo is not None and memo in puzzle_hashes):
                        transaction_ids.append(item.spend_bundle_name)
                        break
                else:
                    continue

                break

        return transaction_ids

    # TODO: move "process_mempool_items()" into this class in order to do this a
    # bit more efficiently
    def items_by_feerate(self) -> Iterator[MempoolItem]:
        return self._map.high_fee_items()

    def size(self) -> int:
        return len(self._map)

    def get_item_by_id(self, item_id: bytes32) -> Optional[MempoolItem]:
        return self._map.get(item_id)

    def get_items_by_coin_id(self, spent_coin_id: bytes32) -> Iterator[MempoolItem]:
        return self._map.items_by_coin_ids([spent_coin_id])

    def get_items_by_coin_ids(self, spent_coin_ids: list[bytes32]) -> list[MempoolItem]:
        return list(self._map.items_by_coin_ids(spent_coin_ids))

    def get_min_fee_rate(self, cost: int) -> Optional[float]:
        """
        Gets the minimum fpc rate that a transaction with specified cost will need in order to get included.
        """

        if not self.at_full_capacity(cost):
            return 0

        # TODO: make MempoolItem.cost be CLVMCost
        current_cost = self._map.total_cost()

        # Iterates through all spends in increasing fee per cost
        for item in self._map.low_fee_items():
            current_cost -= item.cost
            # Removing one at a time, until our transaction of size cost fits
            if current_cost + cost <= self.mempool_info.max_size_in_cost:
                return item.fee_per_cost

        log.info(
            f"Transaction with cost {cost} does not fit in mempool of max cost {self.mempool_info.max_size_in_cost}"
        )
        return None

    def new_tx_block(self, block_height: uint32, timestamp: uint64) -> MempoolRemoveInfo:
        """
        Remove all items that became invalid because of this new height and
        timestamp. (we don't know about which coins were spent in this new block
        here, so those are handled separately)
        """
        expired = chain(
            self._map.expiring_soon_height_items(block_height),
            self._map.expiring_soon_seconds_items(timestamp),
        )

        self._block_height = block_height
        self._timestamp = timestamp

        return self.remove_from_pool([item.spend_bundle_name for item in expired], MempoolRemoveReason.EXPIRED)

    def remove_from_pool(self, items: list[bytes32], reason: MempoolRemoveReason) -> MempoolRemoveInfo:
        """
        Removes an item from the mempool.
        """
        if items == []:
            return MempoolRemoveInfo([], reason)

        removed_items: list[MempoolItem] = []

        for transaction_id in items:
            item = self._map.remove(transaction_id)

            if item is not None:
                removed_items.append(item)

        if reason != MempoolRemoveReason.BLOCK_INCLUSION:
            info = FeeMempoolInfo(
                self.mempool_info, self.total_mempool_cost(), self.total_mempool_fees(), datetime.now()
            )
            for item in removed_items:
                self.fee_estimator.remove_mempool_item(
                    info, MempoolItemInfo(item.cost, item.fee, item.height_added_to_mempool)
                )

        return MempoolRemoveInfo(removed_items, reason)

    def add_to_pool(self, item: MempoolItem) -> MempoolAddInfo:
        """
        Adds an item to the mempool by kicking out transactions (if it doesn't fit), in order of increasing fee per cost
        """

        assert item.fee < MEMPOOL_ITEM_FEE_LIMIT
        assert item.conds is not None
        assert item.cost <= self.mempool_info.max_block_clvm_cost

        removals: list[MempoolRemoveInfo] = []

        # we have certain limits on transactions that will expire soon
        # (in the next 15 minutes)
        block_cutoff = self._block_height + 48
        time_cutoff = self._timestamp + 900
        if (item.assert_before_height is not None and item.assert_before_height < block_cutoff) or (
            item.assert_before_seconds is not None and item.assert_before_seconds < time_cutoff
        ):
            # this lists only transactions that expire soon, in order of
            # lowest fee rate along with the cumulative cost of such
            # transactions counting from highest to lowest fee rate
            expiring_soon = list(
                chain(
                    self._map.expiring_soon_height_items(uint32(block_cutoff - 1)),
                    self._map.expiring_soon_seconds_items(uint64(time_cutoff - 1)),
                )
            )
            expiring_soon.sort(key=lambda tx: -tx.fee_per_cost)

            to_remove: list[bytes32] = []

            cumulative_cost = 0

            for expiring_item in expiring_soon:
                cumulative_cost += expiring_item.cost

                # there's space for us, stop pruning
                if cumulative_cost + item.cost <= self.mempool_info.max_block_clvm_cost:
                    break

                # we can't evict any more transactions, abort (and don't
                # evict what we put aside in "to_remove" list)
                if expiring_item.fee_per_cost > item.fee_per_cost:
                    return MempoolAddInfo([], Err.INVALID_FEE_LOW_FEE)

                to_remove.append(expiring_item.spend_bundle_name)

            removals.append(self.remove_from_pool(to_remove, MempoolRemoveReason.EXPIRED))

            # if we don't find any entries, it's OK to add this entry

        if self._map.total_cost() + item.cost > self.mempool_info.max_size_in_cost:
            # pick the items with the lowest fee per cost to remove
            to_remove = []

            cumulative_cost = 0

            for low_fee in self._map.low_fee_items():
                if cumulative_cost + item.cost <= self.mempool_info.max_size_in_cost:
                    break

                cumulative_cost += low_fee.cost
                to_remove.append(low_fee.spend_bundle_name)

            removals.append(self.remove_from_pool(to_remove, MempoolRemoveReason.POOL_FULL))

        self._map.add(item)

        info = FeeMempoolInfo(self.mempool_info, self.total_mempool_cost(), self.total_mempool_fees(), datetime.now())
        self.fee_estimator.add_mempool_item(info, MempoolItemInfo(item.cost, item.fee, item.height_added_to_mempool))
        return MempoolAddInfo(removals, None)

    # each tuple holds new_coin_id, current_coin_id, mempool item name
    def update_spend_index(self, spends_to_update: list[tuple[bytes32, bytes32, bytes32]]) -> None:
        for new_coin_id, coin_id, transaction_id in spends_to_update:
            self._map.update_coin_index(transaction_id, coin_id, new_coin_id)

    def at_full_capacity(self, cost: int) -> bool:
        """
        Checks whether the mempool is at full capacity and cannot accept a transaction with size cost.
        """

        return self._map.total_cost() + cost > self.mempool_info.max_size_in_cost

    async def create_block_generator(
        self,
        get_unspent_lineage_info_for_puzzle_hash: Callable[[bytes32], Awaitable[Optional[UnspentLineageInfo]]],
        constants: ConsensusConstants,
        height: uint32,
        timeout: float,
    ) -> Optional[NewBlockGenerator]:
        """
        height is needed in case we fast-forward a transaction and we need to
        re-run its puzzle.
        """

        mempool_bundle = await self.create_bundle_from_mempool_items(
            get_unspent_lineage_info_for_puzzle_hash,
            constants,
            height,
            timeout,
        )
        if mempool_bundle is None:
            return None

        spend_bundle, additions = mempool_bundle
        removals = spend_bundle.removals()
        log.info(f"Add rem: {len(additions)} {len(removals)}")

        # since the hard fork has activated, block generators are
        # allowed to be serialized with CLVM back-references. We can do that
        # unconditionally.
        start_time = monotonic()
        spends = [(cs.coin, bytes(cs.puzzle_reveal), bytes(cs.solution)) for cs in spend_bundle.coin_spends]
        block_program = solution_generator_backrefs(spends)

        duration = monotonic() - start_time
        log.log(
            logging.INFO if duration < 1 else logging.WARNING,
            f"serializing block generator took {duration:0.2f} seconds "
            f"spends: {len(removals)} additions: {len(additions)}",
        )

        flags = get_flags_for_height_and_constants(height, constants) | MEMPOOL_MODE | DONT_VALIDATE_SIGNATURE

        _, conds = run_block_generator2(
            block_program,
            [],
            constants.MAX_BLOCK_COST_CLVM,
            flags,
            spend_bundle.aggregated_signature,
            None,
            constants,
        )

        assert conds is not None
        assert conds.cost > 0

        return NewBlockGenerator(
            SerializedProgram.from_bytes(block_program),
            [],
            [],
            spend_bundle.aggregated_signature,
            additions,
            removals,
            uint64(conds.cost),
        )

    async def create_bundle_from_mempool_items(
        self,
        get_unspent_lineage_info_for_puzzle_hash: Callable[[bytes32], Awaitable[Optional[UnspentLineageInfo]]],
        constants: ConsensusConstants,
        height: uint32,
        timeout: float = 1.0,
    ) -> Optional[tuple[SpendBundle, list[Coin]]]:
        cost_sum = 0  # Checks that total cost does not exceed block maximum
        fee_sum = 0  # Checks that total fees don't exceed 64 bits
        processed_spend_bundles = 0
        additions: list[Coin] = []
        # This contains:
        # 1. A map of coin ID to a coin spend solution and its isolated cost
        #   We reconstruct it for every bundle we create from mempool items because we
        #   deduplicate on the first coin spend solution that comes with the highest
        #   fee rate item, and that can change across calls
        # 2. A map of fast forward eligible singleton puzzle hash to the most
        #   recent unspent singleton data, to allow chaining fast forward
        #   singleton spends
        eligible_coin_spends = EligibleCoinSpends()
        coin_spends: list[CoinSpend] = []
        sigs: list[G2Element] = []
        log.info(f"Starting to make block, max cost: {self.mempool_info.max_block_clvm_cost}")
        bundle_creation_start = monotonic()
        skipped_items = 0

        for item in self._map.high_fee_items():
            current_time = monotonic()
            if current_time - bundle_creation_start >= timeout:
                log.info(f"exiting early, already spent {current_time - bundle_creation_start:0.2f} s")
                break
            try:
                assert item.conds is not None
                cost = item.conds.cost
                if skipped_items >= PRIORITY_TX_THRESHOLD:
                    # If we've encountered `PRIORITY_TX_THRESHOLD` number of
                    # transactions that don't fit in the remaining block size,
                    # we want to keep looking for smaller transactions that
                    # might fit, but we also want to avoid spending too much
                    # time on potentially expensive ones, hence this shortcut.
                    if any(
                        map(
                            lambda spend_data: (spend_data.eligible_for_dedup or spend_data.eligible_for_fast_forward),
                            item.bundle_coin_spends.values(),
                        )
                    ):
                        log.info("Skipping transaction with dedup or FF spends {item.name}")
                        continue

                    unique_coin_spends = []
                    unique_additions = []
                    for spend_data in item.bundle_coin_spends.values():
                        unique_coin_spends.append(spend_data.coin_spend)
                        unique_additions.extend(spend_data.additions)
                    cost_saving = 0
                else:
                    bundle_coin_spends = await eligible_coin_spends.process_fast_forward_spends(
                        mempool_item=item,
                        get_unspent_lineage_info_for_puzzle_hash=get_unspent_lineage_info_for_puzzle_hash,
                        height=height,
                        constants=constants,
                    )
                    unique_coin_spends, cost_saving, unique_additions = eligible_coin_spends.get_deduplication_info(
                        bundle_coin_spends=bundle_coin_spends, max_cost=cost
                    )
                item_cost = cost - cost_saving
                log.info(
                    "Cumulative cost: %d, fee per cost: %0.4f, item cost: %d", cost_sum, item.fee / item_cost, item_cost
                )
                new_fee_sum = fee_sum + item.fee
                if new_fee_sum > DEFAULT_CONSTANTS.MAX_COIN_AMOUNT:
                    # Such a fee is very unlikely to happen but we're defensively
                    # accounting for it
                    break  # pragma: no cover
                new_cost_sum = cost_sum + item_cost
                if new_cost_sum > self.mempool_info.max_block_clvm_cost:
                    # Let's skip this item
                    log.info(
                        "Skipping mempool item. Cumulative cost %d exceeds maximum block cost %d",
                        new_cost_sum,
                        self.mempool_info.max_block_clvm_cost,
                    )
                    skipped_items += 1
                    if skipped_items < MAX_SKIPPED_ITEMS:
                        continue
                    # Let's stop taking more items if we skipped `MAX_SKIPPED_ITEMS`
                    break
                coin_spends.extend(unique_coin_spends)
                additions.extend(unique_additions)
                sigs.append(item.spend_bundle.aggregated_signature)
                cost_sum = new_cost_sum
                fee_sum = new_fee_sum
                processed_spend_bundles += 1
                # Let's stop taking more items if we don't have enough cost left
                # for at least `MIN_COST_THRESHOLD` because that would mean we're
                # getting very close to the limit anyway and *probably* won't
                # find transactions small enough to fit at this point
                if self.mempool_info.max_block_clvm_cost - cost_sum < MIN_COST_THRESHOLD:
                    break
            except SkipDedup as e:
                log.info(f"{e}")
                continue
            except Exception as e:
                log.info(f"Exception while checking a mempool item for deduplication: {e}")
                skipped_items += 1
                continue
        if coin_spends == []:
            return None
        log.info(
            f"Cumulative cost of block (real cost should be less) {cost_sum}. Proportion "
            f"full: {cost_sum / self.mempool_info.max_block_clvm_cost}"
        )
        aggregated_signature = AugSchemeMPL.aggregate(sigs)
        agg = SpendBundle(coin_spends, aggregated_signature)
        bundle_creation_end = monotonic()
        duration = bundle_creation_end - bundle_creation_start
        log.log(
            logging.INFO if duration < 1 else logging.WARNING,
            f"create_bundle_from_mempool_items took {duration:0.4f} seconds",
        )
        return agg, additions

    async def create_block_generator2(
        self,
        get_unspent_lineage_info_for_puzzle_hash: Callable[[bytes32], Awaitable[Optional[UnspentLineageInfo]]],
        constants: ConsensusConstants,
        height: uint32,
        timeout: float,
    ) -> Optional[NewBlockGenerator]:
        fee_sum = 0  # Checks that total fees don't exceed 64 bits
        additions: list[Coin] = []
        removals: list[Coin] = []

        eligible_coin_spends = EligibleCoinSpends()
        log.info(f"Starting to make block, max cost: {self.mempool_info.max_block_clvm_cost}")
        generator_creation_start = monotonic()
        builder = BlockBuilder()
        skipped_items = 0
        # the total (estimated) cost of the transactions added so far
        block_cost = 0
        added_spends = 0

        batch_transactions: list[SpendBundle] = []
        batch_additions: list[Coin] = []
        batch_spends = 0
        # this cost only includes conditions and execution cost, not byte-cost
        batch_cost = 0

        for item in self._map.high_fee_items():
            current_time = monotonic()
            if current_time - generator_creation_start >= timeout:
                log.info(f"exiting early, already spent {current_time - generator_creation_start:0.2f} s")
                break

            try:
                assert item.conds is not None
                cost = item.conds.condition_cost + item.conds.execution_cost
                await eligible_coin_spends.process_fast_forward_spends(
                    mempool_item=item,
                    get_unspent_lineage_info_for_puzzle_hash=get_unspent_lineage_info_for_puzzle_hash,
                    height=height,
                    constants=constants,
                )
                unique_coin_spends, cost_saving, unique_additions = eligible_coin_spends.get_deduplication_info(
                    bundle_coin_spends=item.bundle_coin_spends, max_cost=cost
                )
                new_fee_sum = fee_sum + item.fee
                if new_fee_sum > DEFAULT_CONSTANTS.MAX_COIN_AMOUNT:
                    # Such a fee is very unlikely to happen but we're defensively
                    # accounting for it
                    break  # pragma: no cover

                # if adding item would make us exceed the block cost, commit the
                # batch we've built up first, to see if more space may be freed
                # up by the compression
                if block_cost + item.conds.cost - cost_saving > constants.MAX_BLOCK_COST_CLVM:
                    added, done = builder.add_spend_bundles(batch_transactions, uint64(batch_cost), constants)

                    block_cost = builder.cost()
                    if added:
                        added_spends += batch_spends
                        additions.extend(batch_additions)
                        removals.extend([cs.coin for sb in batch_transactions for cs in sb.coin_spends])
                        log.info(
                            f"adding TX batch, additions: {len(batch_additions)} removals: {batch_spends} "
                            f"cost: {batch_cost} total cost: {block_cost}"
                        )
                    else:
                        skipped_items += 1

                    batch_cost = 0
                    batch_transactions = []
                    batch_additions = []
                    batch_spends = 0
                    if done:
                        break

                batch_cost += cost - cost_saving
                batch_transactions.append(SpendBundle(unique_coin_spends, item.spend_bundle.aggregated_signature))
                batch_spends += len(unique_coin_spends)
                batch_additions.extend(unique_additions)
                fee_sum = new_fee_sum
                block_cost += item.conds.cost - cost_saving
            except SkipDedup as e:
                log.info(f"{e}")
                continue
            except Exception as e:
                log.info(f"Exception while checking a mempool item for deduplication: {e}")
                skipped_items += 1
                continue

        if len(batch_transactions) > 0:
            added, _ = builder.add_spend_bundles(batch_transactions, uint64(batch_cost), constants)

            if added:
                added_spends += batch_spends
                additions.extend(batch_additions)
                removals.extend([cs.coin for sb in batch_transactions for cs in sb.coin_spends])
                block_cost = builder.cost()
                log.info(
                    f"adding TX batch, additions: {len(batch_additions)} removals: {batch_spends} "
                    f"cost: {batch_cost} total cost: {block_cost}"
                )

        if removals == []:
            return None

        generator_creation_end = monotonic()
        duration = generator_creation_end - generator_creation_start
        block_program, signature, cost = builder.finalize(constants)
        log.log(
            logging.INFO if duration < 2 else logging.WARNING,
            f"create_block_generator2() took {duration:0.4f} seconds. "
            f"block cost: {cost} spends: {added_spends} additions: {len(additions)}",
        )
        assert block_cost == cost

        return NewBlockGenerator(
            SerializedProgram.from_bytes(block_program),
            [],
            [],
            signature,
            additions,
            removals,
            uint64(block_cost),
        )
