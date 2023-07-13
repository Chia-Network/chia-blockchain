from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from blspy import AugSchemeMPL, G2Element
from chia_rs import Coin

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.fee_estimation import FeeMempoolInfo, MempoolInfo, MempoolItemInfo
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.clvm_cost import CLVMCost
from chia.types.coin_spend import CoinSpend
from chia.types.eligible_coin_spends import EligibleCoinSpends
from chia.types.internal_mempool_item import InternalMempoolItem
from chia.types.mempool_item import MempoolItem
from chia.types.spend_bundle import SpendBundle
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER
from chia.util.errors import Err
from chia.util.ints import uint32, uint64
from chia.util.misc import to_batches

log = logging.getLogger(__name__)

# We impose a limit on the fee a single transaction can pay in order to have the
# sum of all fees in the mempool be less than 2^63. That's the limit of sqlite's
# integers, which we rely on for computing fee per cost as well as the fee sum
MEMPOOL_ITEM_FEE_LIMIT = 2**50


class MempoolRemoveReason(Enum):
    CONFLICT = 1
    BLOCK_INCLUSION = 2
    POOL_FULL = 3
    EXPIRED = 4


class Mempool:
    _db_conn: sqlite3.Connection
    # it's expensive to serialize and deserialize G2Element, so we keep those in
    # this separate dictionary
    _items: Dict[bytes32, InternalMempoolItem]

    # the most recent block height and timestamp that we know of
    _block_height: uint32
    _timestamp: uint64

    def __init__(self, mempool_info: MempoolInfo, fee_estimator: FeeEstimatorInterface):
        self._db_conn = sqlite3.connect(":memory:")
        self._items = {}
        self._block_height = uint32(0)
        self._timestamp = uint64(0)

        with self._db_conn:
            # name means SpendBundle hash
            # assert_height may be NIL
            # the seq field indicates the order of items being added to the
            # mempool. It's used as a tie-breaker for items with the same fee
            # rate
            # TODO: In the future, for the "fee_per_cost" field, opt for
            # "GENERATED ALWAYS AS (CAST(fee AS REAL) / cost) VIRTUAL"
            self._db_conn.execute(
                """CREATE TABLE tx(
                name BLOB,
                cost INT NOT NULL,
                fee INT NOT NULL,
                assert_height INT,
                assert_before_height INT,
                assert_before_seconds INT,
                fee_per_cost REAL,
                seq INTEGER PRIMARY KEY AUTOINCREMENT)
                """
            )
            self._db_conn.execute("CREATE INDEX name_idx ON tx(name)")
            self._db_conn.execute("CREATE INDEX fee_sum ON tx(fee)")
            self._db_conn.execute("CREATE INDEX cost_sum ON tx(cost)")
            self._db_conn.execute("CREATE INDEX feerate ON tx(fee_per_cost)")
            self._db_conn.execute(
                "CREATE INDEX assert_before ON tx(assert_before_height, assert_before_seconds) "
                "WHERE assert_before_height IS NOT NULL OR assert_before_seconds IS NOT NULL"
            )

            # This table maps coin IDs to spend bundles hashes
            self._db_conn.execute(
                """CREATE TABLE spends(
                coin_id BLOB NOT NULL,
                tx BLOB NOT NULL,
                UNIQUE(coin_id, tx))
                """
            )
            self._db_conn.execute("CREATE INDEX spend_by_coin ON spends(coin_id)")
            self._db_conn.execute("CREATE INDEX spend_by_bundle ON spends(tx)")

        self.mempool_info: MempoolInfo = mempool_info
        self.fee_estimator: FeeEstimatorInterface = fee_estimator

    def __del__(self) -> None:
        self._db_conn.close()

    def _row_to_item(self, row: sqlite3.Row) -> MempoolItem:
        name = bytes32(row[0])
        fee = int(row[2])
        assert_height = row[3]
        assert_before_height = row[4]
        assert_before_seconds = row[5]
        item = self._items[name]

        return MempoolItem(
            item.spend_bundle,
            uint64(fee),
            item.npc_result,
            name,
            uint32(item.height_added_to_mempool),
            assert_height,
            assert_before_height,
            assert_before_seconds,
            bundle_coin_spends=item.bundle_coin_spends,
        )

    def total_mempool_fees(self) -> int:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT SUM(fee) FROM tx")
            val = cursor.fetchone()[0]
            return uint64(0) if val is None else uint64(val)

    def total_mempool_cost(self) -> CLVMCost:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT SUM(cost) FROM tx")
            val = cursor.fetchone()[0]
            return CLVMCost(uint64(0) if val is None else uint64(val))

    def all_items(self) -> Iterator[MempoolItem]:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT * FROM tx")
            for row in cursor:
                yield self._row_to_item(row)

    def all_item_ids(self) -> List[bytes32]:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT name FROM tx")
            return [bytes32(row[0]) for row in cursor]

    # TODO: move "process_mempool_items()" into this class in order to do this a
    # bit more efficiently
    def items_by_feerate(self) -> Iterator[MempoolItem]:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT * FROM tx ORDER BY fee_per_cost DESC, seq ASC")
            for row in cursor:
                yield self._row_to_item(row)

    def size(self) -> int:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT Count(name) FROM tx")
            val = cursor.fetchone()
            return 0 if val is None else int(val[0])

    def get_item_by_id(self, item_id: bytes32) -> Optional[MempoolItem]:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT * FROM tx WHERE name=?", (item_id,))
            row = cursor.fetchone()
            return None if row is None else self._row_to_item(row)

    # TODO: we need a bulk lookup function like this too
    def get_items_by_coin_id(self, spent_coin_id: bytes32) -> List[MempoolItem]:
        with self._db_conn:
            cursor = self._db_conn.execute(
                "SELECT * FROM tx WHERE name in (SELECT tx FROM spends WHERE coin_id=?)",
                (spent_coin_id,),
            )
            return [self._row_to_item(row) for row in cursor]

    def get_items_by_coin_ids(self, spent_coin_ids: List[bytes32]) -> List[MempoolItem]:
        items: List[MempoolItem] = []
        for batch in to_batches(spent_coin_ids, SQLITE_MAX_VARIABLE_NUMBER):
            args = ",".join(["?"] * len(batch.entries))
            with self._db_conn:
                cursor = self._db_conn.execute(
                    f"SELECT * FROM tx WHERE name IN (SELECT tx FROM spends WHERE coin_id IN ({args}))",
                    tuple(batch.entries),
                )
                items.extend(self._row_to_item(row) for row in cursor)
        return items

    def get_min_fee_rate(self, cost: int) -> float:
        """
        Gets the minimum fpc rate that a transaction with specified cost will need in order to get included.
        """

        if self.at_full_capacity(cost):
            # TODO: make MempoolItem.cost be CLVMCost
            current_cost = int(self.total_mempool_cost())

            # Iterates through all spends in increasing fee per cost
            with self._db_conn:
                cursor = self._db_conn.execute("SELECT cost,fee_per_cost FROM tx ORDER BY fee_per_cost ASC, seq DESC")

                item_cost: int
                fee_per_cost: float
                for item_cost, fee_per_cost in cursor:
                    current_cost -= item_cost
                    # Removing one at a time, until our transaction of size cost fits
                    if current_cost + cost <= self.mempool_info.max_size_in_cost:
                        return fee_per_cost

            raise ValueError(
                f"Transaction with cost {cost} does not fit in mempool of max cost {self.mempool_info.max_size_in_cost}"
            )
        else:
            return 0

    def new_tx_block(self, block_height: uint32, timestamp: uint64) -> None:
        """
        Remove all items that became invalid because of this new height and
        timestamp. (we don't know about which coins were spent in this new block
        here, so those are handled separately)
        """
        with self._db_conn:
            cursor = self._db_conn.execute(
                "SELECT name FROM tx WHERE assert_before_seconds <= ? OR assert_before_height <= ?",
                (timestamp, block_height),
            )
            to_remove = [bytes32(row[0]) for row in cursor]

        self.remove_from_pool(to_remove, MempoolRemoveReason.EXPIRED)
        self._block_height = block_height
        self._timestamp = timestamp

    def remove_from_pool(self, items: List[bytes32], reason: MempoolRemoveReason) -> None:
        """
        Removes an item from the mempool.
        """
        if items == []:
            return

        removed_items: List[MempoolItemInfo] = []
        if reason != MempoolRemoveReason.BLOCK_INCLUSION:
            for batch in to_batches(items, SQLITE_MAX_VARIABLE_NUMBER):
                args = ",".join(["?"] * len(batch.entries))
                with self._db_conn:
                    cursor = self._db_conn.execute(
                        f"SELECT name, cost, fee FROM tx WHERE name in ({args})", batch.entries
                    )
                    for row in cursor:
                        name = bytes32(row[0])
                        internal_item = self._items[name]
                        item = MempoolItemInfo(int(row[1]), int(row[2]), internal_item.height_added_to_mempool)
                        removed_items.append(item)

        for name in items:
            self._items.pop(name)

        for batch in to_batches(items, SQLITE_MAX_VARIABLE_NUMBER):
            args = ",".join(["?"] * len(batch.entries))
            with self._db_conn:
                self._db_conn.execute(f"DELETE FROM tx WHERE name in ({args})", batch.entries)
                self._db_conn.execute(f"DELETE FROM spends WHERE tx in ({args})", batch.entries)

        if reason != MempoolRemoveReason.BLOCK_INCLUSION:
            info = FeeMempoolInfo(
                self.mempool_info, self.total_mempool_cost(), self.total_mempool_fees(), datetime.now()
            )
            for iteminfo in removed_items:
                self.fee_estimator.remove_mempool_item(info, iteminfo)

    def add_to_pool(self, item: MempoolItem) -> Optional[Err]:
        """
        Adds an item to the mempool by kicking out transactions (if it doesn't fit), in order of increasing fee per cost
        """

        assert item.fee < MEMPOOL_ITEM_FEE_LIMIT
        assert item.npc_result.conds is not None
        assert item.cost <= self.mempool_info.max_block_clvm_cost

        with self._db_conn:
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
                cursor = self._db_conn.execute(
                    """
                    SELECT name,
                        fee_per_cost,
                        SUM(cost) OVER (ORDER BY fee_per_cost DESC, seq ASC) AS cumulative_cost
                    FROM tx
                    WHERE assert_before_seconds IS NOT NULL AND assert_before_seconds < ?
                        OR assert_before_height IS NOT NULL AND assert_before_height < ?
                    ORDER BY cumulative_cost DESC
                    """,
                    (time_cutoff, block_cutoff),
                )
                to_remove: List[bytes32] = []
                for row in cursor:
                    name, fee_per_cost, cumulative_cost = row

                    # there's space for us, stop pruning
                    if cumulative_cost + item.cost <= self.mempool_info.max_block_clvm_cost:
                        break

                    # we can't evict any more transactions, abort (and don't
                    # evict what we put aside in "to_remove" list)
                    if fee_per_cost > item.fee_per_cost:
                        return Err.INVALID_FEE_LOW_FEE
                    to_remove.append(name)
                self.remove_from_pool(to_remove, MempoolRemoveReason.EXPIRED)
                # if we don't find any entries, it's OK to add this entry

            total_cost = int(self.total_mempool_cost())
            if total_cost + item.cost > self.mempool_info.max_size_in_cost:
                # pick the items with the lowest fee per cost to remove
                cursor = self._db_conn.execute(
                    """SELECT name FROM tx
                    WHERE name NOT IN (
                        SELECT name FROM (
                            SELECT name,
                            SUM(cost) OVER (ORDER BY fee_per_cost DESC, seq ASC) AS total_cost
                            FROM tx) AS tx_with_cost
                        WHERE total_cost <= ?)
                    """,
                    (self.mempool_info.max_size_in_cost - item.cost,),
                )
                to_remove = [bytes32(row[0]) for row in cursor]
                self.remove_from_pool(to_remove, MempoolRemoveReason.POOL_FULL)

            # TODO: In the future, for the "fee_per_cost" field, opt for
            # "GENERATED ALWAYS AS (CAST(fee AS REAL) / cost) VIRTUAL"
            self._db_conn.execute(
                "INSERT INTO "
                "tx(name,cost,fee,assert_height,assert_before_height,assert_before_seconds,fee_per_cost) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    item.name,
                    item.cost,
                    item.fee,
                    item.assert_height,
                    item.assert_before_height,
                    item.assert_before_seconds,
                    item.fee / item.cost,
                ),
            )

            all_coin_spends = [(s.coin_id, item.name) for s in item.npc_result.conds.spends]
            self._db_conn.executemany("INSERT INTO spends VALUES(?, ?)", all_coin_spends)

            self._items[item.name] = InternalMempoolItem(
                item.spend_bundle, item.npc_result, item.height_added_to_mempool, item.bundle_coin_spends
            )

        info = FeeMempoolInfo(self.mempool_info, self.total_mempool_cost(), self.total_mempool_fees(), datetime.now())
        self.fee_estimator.add_mempool_item(info, MempoolItemInfo(item.cost, item.fee, item.height_added_to_mempool))
        return None

    def at_full_capacity(self, cost: int) -> bool:
        """
        Checks whether the mempool is at full capacity and cannot accept a transaction with size cost.
        """

        return self.total_mempool_cost() + cost > self.mempool_info.max_size_in_cost

    def create_bundle_from_mempool_items(
        self, item_inclusion_filter: Callable[[bytes32], bool]
    ) -> Optional[Tuple[SpendBundle, List[Coin]]]:
        cost_sum = 0  # Checks that total cost does not exceed block maximum
        fee_sum = 0  # Checks that total fees don't exceed 64 bits
        processed_spend_bundles = 0
        additions: List[Coin] = []
        # This contains a map of coin ID to a coin spend solution and its isolated cost
        # We reconstruct it for every bundle we create from mempool items because we
        # deduplicate on the first coin spend solution that comes with the highest
        # fee rate item, and that can change across calls
        eligible_coin_spends = EligibleCoinSpends()
        coin_spends: List[CoinSpend] = []
        sigs: List[G2Element] = []
        log.info(f"Starting to make block, max cost: {self.mempool_info.max_block_clvm_cost}")
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT name, fee FROM tx ORDER BY fee_per_cost DESC, seq ASC")
        for row in cursor:
            name = bytes32(row[0])
            fee = int(row[1])
            item = self._items[name]
            if not item_inclusion_filter(name):
                continue
            try:
                unique_coin_spends, cost_saving, unique_additions = eligible_coin_spends.get_deduplication_info(
                    bundle_coin_spends=item.bundle_coin_spends, max_cost=item.npc_result.cost
                )
                item_cost = item.npc_result.cost - cost_saving
                log.info("Cumulative cost: %d, fee per cost: %0.4f", cost_sum, fee / item_cost)
                if (
                    item_cost + cost_sum > self.mempool_info.max_block_clvm_cost
                    or fee + fee_sum > DEFAULT_CONSTANTS.MAX_COIN_AMOUNT
                ):
                    break
                coin_spends.extend(unique_coin_spends)
                additions.extend(unique_additions)
                sigs.append(item.spend_bundle.aggregated_signature)
                cost_sum += item_cost
                fee_sum += fee
                processed_spend_bundles += 1
            except Exception as e:
                log.debug(f"Exception while checking a mempool item for deduplication: {e}")
                continue
        if processed_spend_bundles == 0:
            return None
        log.info(
            f"Cumulative cost of block (real cost should be less) {cost_sum}. Proportion "
            f"full: {cost_sum / self.mempool_info.max_block_clvm_cost}"
        )
        aggregated_signature = AugSchemeMPL.aggregate(sigs)
        agg = SpendBundle(coin_spends, aggregated_signature)
        return agg, additions
