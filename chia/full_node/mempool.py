from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Iterator, List, Optional

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.fee_estimation import FeeMempoolInfo, MempoolInfo, MempoolItemInfo
from chia.full_node.fee_estimator_interface import FeeEstimatorInterface
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.clvm_cost import CLVMCost
from chia.types.mempool_item import MempoolItem
from chia.types.spend_bundle import SpendBundle
from chia.util.chunks import chunks
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER
from chia.util.ints import uint32, uint64

# We impose a limit on the fee a single transaction can pay in order to have the
# sum of all fees in the mempool be less than 2^63. That's the limit of sqlite's
# integers, which we rely on for computing fee per cost as well as the fee sum
MEMPOOL_ITEM_FEE_LIMIT = 2**50

SQLITE_NO_GENERATED_COLUMNS: bool = sqlite3.sqlite_version_info < (3, 31, 0)


class MempoolRemoveReason(Enum):
    CONFLICT = 1
    BLOCK_INCLUSION = 2
    POOL_FULL = 3
    EXPIRED = 4


@dataclass(frozen=True)
class InternalMempoolItem:
    spend_bundle: SpendBundle
    npc_result: NPCResult
    height_added_to_mempool: uint32


class Mempool:
    _db_conn: sqlite3.Connection
    # it's expensive to serialize and deserialize G2Element, so we keep those in
    # this separate dictionary
    _items: Dict[bytes32, InternalMempoolItem]

    def __init__(self, mempool_info: MempoolInfo, fee_estimator: FeeEstimatorInterface):
        self._db_conn = sqlite3.connect(":memory:")
        self._items = {}

        with self._db_conn:
            # name means SpendBundle hash
            # assert_height may be NIL
            generated = ""
            if not SQLITE_NO_GENERATED_COLUMNS:
                generated = " GENERATED ALWAYS AS (CAST(fee AS REAL) / cost) VIRTUAL"

            self._db_conn.execute(
                f"""CREATE TABLE tx(
                name BLOB PRIMARY KEY,
                cost INT NOT NULL,
                fee INT NOT NULL,
                assert_height INT,
                assert_before_height INT,
                assert_before_seconds INT,
                fee_per_cost REAL{generated})
                """
            )
            self._db_conn.execute("CREATE INDEX fee_sum ON tx(fee)")
            self._db_conn.execute("CREATE INDEX cost_sum ON tx(cost)")
            self._db_conn.execute("CREATE INDEX feerate ON tx(fee_per_cost)")
            self._db_conn.execute(
                "CREATE INDEX assert_before_height ON tx(assert_before_height) WHERE assert_before_height != NULL"
            )
            self._db_conn.execute(
                "CREATE INDEX assert_before_seconds ON tx(assert_before_seconds) WHERE assert_before_seconds != NULL"
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
        fee = int(row[1])
        assert_height = row[2]
        item = self._items[name]

        return MempoolItem(
            item.spend_bundle, uint64(fee), item.npc_result, name, uint32(item.height_added_to_mempool), assert_height
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

    def all_spends(self) -> Iterator[MempoolItem]:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT name, fee, assert_height FROM tx")
            for row in cursor:
                yield self._row_to_item(row)

    def all_spend_ids(self) -> List[bytes32]:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT name FROM tx")
            return [bytes32(row[0]) for row in cursor]

    # TODO: move "process_mempool_items()" into this class in order to do this a
    # bit more efficiently
    def spends_by_feerate(self) -> Iterator[MempoolItem]:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT name, fee, assert_height FROM tx ORDER BY fee_per_cost DESC")
            for row in cursor:
                yield self._row_to_item(row)

    def size(self) -> int:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT Count(name) FROM tx")
            val = cursor.fetchone()
            return 0 if val is None else int(val[0])

    def get_spend_by_id(self, spend_bundle_id: bytes32) -> Optional[MempoolItem]:
        with self._db_conn:
            cursor = self._db_conn.execute("SELECT name, fee, assert_height FROM tx WHERE name=?", (spend_bundle_id,))
            row = cursor.fetchone()
            return None if row is None else self._row_to_item(row)

    # TODO: we need a bulk lookup function like this too
    def get_spends_by_coin_id(self, spent_coin_id: bytes32) -> List[MempoolItem]:
        with self._db_conn:
            cursor = self._db_conn.execute(
                "SELECT name, fee, assert_height FROM tx WHERE name in (SELECT tx FROM spends WHERE coin_id=?)",
                (spent_coin_id,),
            )
            return [self._row_to_item(row) for row in cursor]

    def get_min_fee_rate(self, cost: int) -> float:
        """
        Gets the minimum fpc rate that a transaction with specified cost will need in order to get included.
        """

        if self.at_full_capacity(cost):
            # TODO: make MempoolItem.cost be CLVMCost
            current_cost = int(self.total_mempool_cost())

            # Iterates through all spends in increasing fee per cost
            with self._db_conn:
                cursor = self._db_conn.execute("SELECT cost,fee_per_cost FROM tx ORDER BY fee_per_cost ASC")

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

    def remove_from_pool(self, items: List[bytes32], reason: MempoolRemoveReason) -> None:
        """
        Removes an item from the mempool.
        """
        if items == []:
            return

        removed_items: List[MempoolItemInfo] = []
        if reason != MempoolRemoveReason.BLOCK_INCLUSION:

            for spend_bundle_ids in chunks(items, SQLITE_MAX_VARIABLE_NUMBER):
                args = ",".join(["?"] * len(spend_bundle_ids))
                with self._db_conn:
                    cursor = self._db_conn.execute(
                        f"SELECT name, cost, fee FROM tx WHERE name in ({args})", spend_bundle_ids
                    )
                    for row in cursor:
                        name = bytes32(row[0])
                        internal_item = self._items[name]
                        item = MempoolItemInfo(int(row[1]), int(row[2]), internal_item.height_added_to_mempool)
                        removed_items.append(item)

        for name in items:
            self._items.pop(name)

        for spend_bundle_ids in chunks(items, SQLITE_MAX_VARIABLE_NUMBER):
            args = ",".join(["?"] * len(spend_bundle_ids))
            with self._db_conn:
                self._db_conn.execute(f"DELETE FROM tx WHERE name in ({args})", spend_bundle_ids)
                self._db_conn.execute(f"DELETE FROM spends WHERE tx in ({args})", spend_bundle_ids)

        if reason != MempoolRemoveReason.BLOCK_INCLUSION:
            info = FeeMempoolInfo(
                self.mempool_info, self.total_mempool_cost(), self.total_mempool_fees(), datetime.now()
            )
            for iteminfo in removed_items:
                self.fee_estimator.remove_mempool_item(info, iteminfo)

    def add_to_pool(self, item: MempoolItem) -> None:
        """
        Adds an item to the mempool by kicking out transactions (if it doesn't fit), in order of increasing fee per cost
        """

        assert item.fee < MEMPOOL_ITEM_FEE_LIMIT
        assert item.npc_result.conds is not None

        # TODO: this block could be simplified by removing all items in a single
        # SQL query. Or at least figure out which items to remove and then
        # remove them all in a single call to remove_from_pool()
        with self._db_conn:
            while self.at_full_capacity(item.cost):
                # pick the item with the lowest fee per cost to remove
                cursor = self._db_conn.execute("SELECT name FROM tx ORDER BY fee_per_cost ASC LIMIT 1")
                name = bytes32(cursor.fetchone()[0])
                self.remove_from_pool([name], MempoolRemoveReason.POOL_FULL)

            if SQLITE_NO_GENERATED_COLUMNS:
                self._db_conn.execute(
                    "INSERT INTO tx VALUES(?, ?, ?, ?, ?, ?, ?)",
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
            else:
                self._db_conn.execute(
                    "INSERT INTO tx VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        item.name,
                        item.cost,
                        item.fee,
                        item.assert_height,
                        item.assert_before_height,
                        item.assert_before_seconds,
                    ),
                )

            all_coin_spends = [(s.coin_id, item.name) for s in item.npc_result.conds.spends]
            self._db_conn.executemany("INSERT INTO spends VALUES(?, ?)", all_coin_spends)

            self._items[item.name] = InternalMempoolItem(
                item.spend_bundle, item.npc_result, item.height_added_to_mempool
            )

        info = FeeMempoolInfo(self.mempool_info, self.total_mempool_cost(), self.total_mempool_fees(), datetime.now())
        self.fee_estimator.add_mempool_item(info, MempoolItemInfo(item.cost, item.fee, item.height_added_to_mempool))

    def at_full_capacity(self, cost: int) -> bool:
        """
        Checks whether the mempool is at full capacity and cannot accept a transaction with size cost.
        """

        return self.total_mempool_cost() + cost > self.mempool_info.max_size_in_cost
