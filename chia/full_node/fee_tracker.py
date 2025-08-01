from __future__ import annotations

import logging
from bisect import bisect_left
from dataclasses import dataclass
from typing import Optional

from chia_rs.sized_ints import uint8, uint32, uint64

from chia.full_node.fee_estimate_store import FeeStore
from chia.full_node.fee_estimation import MempoolItemInfo
from chia.full_node.fee_estimator_constants import (
    FEE_ESTIMATOR_VERSION,
    INFINITE_FEE_RATE,
    INITIAL_STEP,
    LONG_BLOCK_PERIOD,
    LONG_DECAY,
    LONG_SCALE,
    MAX_FEE_RATE,
    MED_BLOCK_PERIOD,
    MED_DECAY,
    MED_SCALE,
    SECONDS_PER_BLOCK,
    SHORT_BLOCK_PERIOD,
    SHORT_DECAY,
    SHORT_SCALE,
    STEP_SIZE,
    SUCCESS_PCT,
    SUFFICIENT_FEE_TXS,
)
from chia.full_node.fee_history import FeeStatBackup, FeeTrackerBackup


@dataclass
class BucketResult:
    start: float
    end: float
    within_target: float
    total_confirmed: float
    in_mempool: float
    left_mempool: float


@dataclass
class EstimateResult:
    requested_time: uint64
    pass_bucket: BucketResult
    fail_bucket: BucketResult
    median: float


def get_estimate_block_intervals() -> list[int]:
    return [
        SHORT_BLOCK_PERIOD * SHORT_SCALE - SHORT_SCALE,
        MED_BLOCK_PERIOD * MED_SCALE - MED_SCALE,
        LONG_BLOCK_PERIOD * LONG_SCALE - LONG_SCALE,
    ]


def get_estimate_time_intervals() -> list[uint64]:
    return [uint64(blocks * SECONDS_PER_BLOCK) for blocks in get_estimate_block_intervals()]


# Implementation of bitcoin core fee estimation algorithm
# https://gist.github.com/morcos/d3637f015bc4e607e1fd10d8351e9f41
class FeeStat:  # TxConfirmStats
    buckets: list[float]  # These elements represent the upper-bound of the range for the bucket

    # For each bucket xL
    # Count the total number of txs in each bucket
    # Track historical moving average of this total over block
    tx_ct_avg: list[float]

    # Count the total number of txs confirmed within Y periods in each bucket
    # Track the historical moving average of these totals over blocks
    confirmed_average: list[list[float]]  # confirmed_average [y][x]

    # Track moving average of txs which have been evicted from the mempool
    # after failing to be confirmed within Y block
    failed_average: list[list[float]]  # failed_average [y][x]

    # Sum the total fee_rate of all txs in each bucket
    # Track historical moving average of this total over blocks
    m_fee_rate_avg: list[float]

    decay: float

    # Resolution of blocks with which confirmations are tracked (number of blocks per period)
    scale: int

    # Mempool counts of outstanding transactions
    # For each bucket x, track the number of transactions in mempool
    # that are unconfirmed for each possible confirmation value y
    unconfirmed_txs: list[list[int]]
    # transactions still unconfirmed after get_max_confirmed for each bucket
    old_unconfirmed_txs: list[int]
    max_confirms: int
    fee_store: FeeStore

    def __init__(
        self,
        buckets: list[float],
        max_periods: int,
        decay: float,
        scale: int,
        fee_store: FeeStore,
        my_type: str,
    ):
        self.buckets = buckets
        self.confirmed_average = [[] for _ in range(max_periods)]
        self.failed_average = [[] for _ in range(max_periods)]
        self.decay = decay
        self.scale = scale
        self.max_confirms = self.scale * len(self.confirmed_average)
        self.log = logging.Logger(__name__)
        self.fee_store = fee_store
        self.type = my_type
        self.max_periods = max_periods

        for i in range(max_periods):
            self.confirmed_average[i] = [0 for _ in range(len(buckets))]
            self.failed_average[i] = [0 for _ in range(len(buckets))]

        self.tx_ct_avg = [0 for _ in range(len(buckets))]
        self.m_fee_rate_avg = [0 for _ in range(len(buckets))]

        self.unconfirmed_txs = [[] for _ in range(self.max_confirms)]
        for i in range(self.max_confirms):
            self.unconfirmed_txs[i] = [0 for _ in range(len(buckets))]

        self.old_unconfirmed_txs = [0 for _ in range(len(buckets))]

    def tx_confirmed(self, blocks_to_confirm: int, item: MempoolItemInfo) -> None:
        if blocks_to_confirm < 1:
            raise ValueError("tx_confirmed called with < 1 block to confirm")

        # convert from number of blocks to number of periods
        periods_to_confirm = int((blocks_to_confirm + self.scale - 1) / self.scale)

        fee_rate = item.fee_per_cost * 1000
        bucket_index = get_bucket_index(self.buckets, fee_rate)

        for i in range(periods_to_confirm, len(self.confirmed_average)):
            self.confirmed_average[i - 1][bucket_index] += 1

        self.tx_ct_avg[bucket_index] += 1
        self.m_fee_rate_avg[bucket_index] += fee_rate

    def update_moving_averages(self) -> None:
        for j in range(len(self.buckets)):
            for i in range(len(self.confirmed_average)):
                self.confirmed_average[i][j] *= self.decay
                self.failed_average[i][j] *= self.decay

            self.tx_ct_avg[j] *= self.decay
            self.m_fee_rate_avg[j] *= self.decay

    def clear_current(self, block_height: uint32) -> None:
        for i in range(len(self.buckets)):
            self.old_unconfirmed_txs[i] += self.unconfirmed_txs[block_height % len(self.unconfirmed_txs)][i]
            self.unconfirmed_txs[block_height % len(self.unconfirmed_txs)][i] = 0

    def new_mempool_tx(self, block_height: uint32, fee_rate: float) -> int:
        bucket_index: int = get_bucket_index(self.buckets, fee_rate)
        block_index = block_height % len(self.unconfirmed_txs)
        self.unconfirmed_txs[block_index][bucket_index] += 1
        return bucket_index

    def remove_tx(self, latest_seen_height: uint32, item: MempoolItemInfo, bucket_index: int) -> None:
        if item.height_added_to_mempool is None:
            return
        block_ago = latest_seen_height - item.height_added_to_mempool
        if latest_seen_height == 0:
            block_ago = 0

        if block_ago < 0:
            return

        if block_ago >= len(self.unconfirmed_txs):
            if self.old_unconfirmed_txs[bucket_index] > 0:
                self.old_unconfirmed_txs[bucket_index] -= 1
        else:
            block_index = item.height_added_to_mempool % len(self.unconfirmed_txs)
            if self.unconfirmed_txs[block_index][bucket_index] > 0:
                self.unconfirmed_txs[block_index][bucket_index] -= 1

        if block_ago >= self.scale:
            periods_ago = block_ago / self.scale
            for i in range(len(self.failed_average)):
                if i >= periods_ago:
                    break
                self.failed_average[i][bucket_index] += 1

    def create_backup(self) -> FeeStatBackup:
        str_tx_ct_abg: list[str] = []
        str_confirmed_average: list[list[str]] = []
        str_failed_average: list[list[str]] = []
        str_m_fee_rate_avg: list[str] = []
        for i in range(self.max_periods):
            str_i_list_conf = []
            for j in range(len(self.confirmed_average[i])):
                str_i_list_conf.append(float.hex(float(self.confirmed_average[i][j])))

            str_confirmed_average.append(str_i_list_conf)

            str_i_list_fail = []
            for j in range(len(self.failed_average[i])):
                str_i_list_fail.append(float.hex(float(self.failed_average[i][j])))

            str_failed_average.append(str_i_list_fail)

        for i in range(len(self.tx_ct_avg)):
            str_tx_ct_abg.append(float.hex(float(self.tx_ct_avg[i])))

        for i in range(len(self.m_fee_rate_avg)):
            str_m_fee_rate_avg.append(float.hex(float(self.m_fee_rate_avg[i])))

        return FeeStatBackup(self.type, str_tx_ct_abg, str_confirmed_average, str_failed_average, str_m_fee_rate_avg)

    def import_backup(self, backup: FeeStatBackup) -> None:
        for i in range(self.max_periods):
            for j in range(len(self.confirmed_average[i])):
                self.confirmed_average[i][j] = float.fromhex(backup.confirmed_average[i][j])
            for j in range(len(self.failed_average[i])):
                self.failed_average[i][j] = float.fromhex(backup.failed_average[i][j])

        for i in range(len(self.tx_ct_avg)):
            self.tx_ct_avg[i] = float.fromhex(backup.tx_ct_avg[i])

        for i in range(len(self.m_fee_rate_avg)):
            self.m_fee_rate_avg[i] = float.fromhex(backup.m_fee_rate_avg[i])

    # See TxConfirmStats::EstimateMedianVal in https://github.com/bitcoin/bitcoin/blob/master/src/policy/fees.cpp
    def estimate_median_val(
        self, conf_target: int, sufficient_tx_val: float, success_break_point: float, block_height: uint32
    ) -> EstimateResult:
        """
        conf_target is the number of blocks within which we hope to get our SpendBundle confirmed
        """
        if conf_target < 0:
            raise ValueError(f"Bad argument to estimate_median_val: conf_target must be >= 0. Got {conf_target}")

        n_conf = 0.0  # Number of txs confirmed within conf_target
        total_num = 0.0  # Total number of txs that were
        extra_num = 0.0
        fail_num = 0.0
        period_target = int((conf_target + self.scale - 1) / self.scale)
        max_bucket_index = len(self.buckets) - 1

        cur_near_bucket = max_bucket_index
        best_near_bucket = max_bucket_index
        cur_far_bucket = max_bucket_index
        best_far_bucket = max_bucket_index

        found_answer = False
        bins = len(self.unconfirmed_txs)
        new_bucket_range = True
        passing = True
        pass_bucket: BucketResult = BucketResult(
            start=0.0,
            end=0.0,
            within_target=0.0,
            total_confirmed=0.0,
            in_mempool=0.0,
            left_mempool=0.0,
        )
        fail_bucket: BucketResult = BucketResult(
            start=0.0,
            end=0.0,
            within_target=0.0,
            total_confirmed=0.0,
            in_mempool=0.0,
            left_mempool=0.0,
        )
        for bucket in range(max_bucket_index, -1, -1):
            if new_bucket_range:
                cur_near_bucket = bucket
                new_bucket_range = False

            cur_far_bucket = bucket
            if period_target - 1 < 0 or period_target - 1 >= len(self.confirmed_average):
                return EstimateResult(
                    requested_time=uint64(conf_target * SECONDS_PER_BLOCK),
                    pass_bucket=pass_bucket,
                    fail_bucket=fail_bucket,
                    median=-1.0,
                )

            ca_len = len(self.confirmed_average[period_target - 1])
            if bucket < 0 or bucket >= ca_len:
                raise RuntimeError(f"bucket index ({bucket}) out of range (0, {ca_len})")

            n_conf += self.confirmed_average[period_target - 1][bucket]
            total_num += self.tx_ct_avg[bucket]
            fail_num += self.failed_average[period_target - 1][bucket]
            for conf_ct in range(conf_target, self.max_confirms):
                extra_num += self.unconfirmed_txs[(block_height - conf_ct) % bins][bucket]
            extra_num += self.old_unconfirmed_txs[bucket]

            # If we have enough transaction data points in this range of buckets,
            # we can test for success
            # (Only count the confirmed data points, so that each confirmation count
            # will be looking at the same amount of data and same bucket breaks)
            if total_num >= sufficient_tx_val / (1 - self.decay):
                curr_pct = n_conf / (total_num + fail_num + extra_num)
                # Check to see if we are no longer getting confirmed at the same rate
                if curr_pct < success_break_point:
                    if passing is True:
                        fail_min_bucket = min(cur_near_bucket, cur_far_bucket)
                        fail_max_bucket = max(cur_near_bucket, cur_far_bucket)
                        self.log.debug(f"Fail_min_bucket: {fail_min_bucket}")
                        fail_bucket = BucketResult(
                            start=self.buckets[fail_min_bucket - 1] if fail_min_bucket else 0,
                            end=self.buckets[fail_max_bucket],
                            within_target=n_conf,
                            total_confirmed=total_num,
                            in_mempool=extra_num,
                            left_mempool=fail_num,
                        )
                        passing = False
                    continue
                else:
                    # Otherwise, update the cumulative stats and bucket variables
                    # and reset the counters
                    found_answer = True
                    passing = True
                    pass_bucket.within_target = n_conf
                    n_conf = 0
                    pass_bucket.total_confirmed = total_num
                    total_num = 0
                    pass_bucket.in_mempool = extra_num
                    pass_bucket.left_mempool = fail_num
                    fail_num = 0
                    extra_num = 0
                    best_near_bucket = cur_near_bucket
                    best_far_bucket = cur_far_bucket
                    new_bucket_range = True
        median = -1.0
        tx_sum = 0.0

        min_bucket = min(best_near_bucket, best_far_bucket)
        max_bucket = max(best_near_bucket, best_far_bucket)

        for i in range(min_bucket, max_bucket + 1):
            tx_sum += self.tx_ct_avg[i]

        if found_answer and tx_sum != 0:
            tx_sum /= 2
            for i in range(min_bucket, max_bucket):
                if self.tx_ct_avg[i] < tx_sum:
                    tx_sum -= self.tx_ct_avg[i]
                else:
                    # This is the correct bucket
                    median = self.m_fee_rate_avg[i] / self.tx_ct_avg[i]
                    break
            pass_bucket.start = self.buckets[min_bucket - 1] if min_bucket else 0
            pass_bucket.end = self.buckets[max_bucket]

        if passing and new_bucket_range is False:
            fail_min_bucket = min(cur_near_bucket, cur_far_bucket)
            fail_max_bucket = max(cur_near_bucket, cur_far_bucket)
            fail_bucket = BucketResult(
                start=self.buckets[fail_min_bucket - 1] if fail_min_bucket else 0,
                end=self.buckets[fail_max_bucket],
                within_target=n_conf,
                total_confirmed=total_num,
                in_mempool=extra_num,
                left_mempool=fail_num,
            )

        passed_within_target_perc = 0.0
        failed_within_target_perc = 0.0
        pass_bucket_total = pass_bucket.total_confirmed + pass_bucket.in_mempool + pass_bucket.left_mempool
        if pass_bucket_total > 0:
            passed_within_target_perc = 100 * pass_bucket.within_target / pass_bucket_total
        fail_bucket_total = fail_bucket.total_confirmed + fail_bucket.in_mempool + fail_bucket.left_mempool
        if fail_bucket_total > 0:
            failed_within_target_perc = 100 * fail_bucket.within_target / fail_bucket_total
        self.log.debug(f"passed_within_target_perc: {passed_within_target_perc}")
        self.log.debug(f"failed_within_target_perc: {failed_within_target_perc}")

        result = EstimateResult(
            requested_time=uint64(conf_target * SECONDS_PER_BLOCK - SECONDS_PER_BLOCK),
            pass_bucket=pass_bucket,
            fail_bucket=fail_bucket,
            median=median,
        )
        return result


def clamp(n: int, smallest: int, largest: int) -> int:
    return max(smallest, min(n, largest))


def get_bucket_index(buckets: list[float], fee_rate: float) -> int:
    if len(buckets) < 1:
        raise RuntimeError(f"get_bucket_index: buckets is invalid ({buckets})")
    # Choose the bucket to the left if we do not have exactly this fee rate
    # Python's list.bisect_left returns the index to insert a new element into a sorted list
    bucket_index = bisect_left(buckets, fee_rate) - 1
    return clamp(bucket_index, 0, len(buckets) - 1)


def init_buckets() -> list[float]:
    fee_rate = INITIAL_STEP

    buckets: list[float] = []
    while fee_rate < MAX_FEE_RATE:
        buckets.append(fee_rate)
        fee_rate *= STEP_SIZE

    buckets.append(INFINITE_FEE_RATE)
    return buckets


class FeeTracker:
    short_horizon: FeeStat
    med_horizon: FeeStat
    long_horizon: FeeStat
    log: logging.Logger
    latest_seen_height: uint32
    first_recorded_height: uint32
    fee_store: FeeStore
    buckets: list[float]

    def __init__(self, fee_store: FeeStore):
        self.log = logging.Logger(__name__)
        self.latest_seen_height = uint32(0)
        self.first_recorded_height = uint32(0)
        self.fee_store = fee_store
        self.buckets = init_buckets()

        self.short_horizon = FeeStat(
            self.buckets,
            SHORT_BLOCK_PERIOD,
            SHORT_DECAY,
            SHORT_SCALE,
            self.fee_store,
            "short",
        )
        self.med_horizon = FeeStat(
            self.buckets,
            MED_BLOCK_PERIOD,
            MED_DECAY,
            MED_SCALE,
            self.fee_store,
            "medium",
        )
        self.long_horizon = FeeStat(
            self.buckets,
            LONG_BLOCK_PERIOD,
            LONG_DECAY,
            LONG_SCALE,
            self.fee_store,
            "long",
        )
        fee_backup: Optional[FeeTrackerBackup] = self.fee_store.get_stored_fee_data()

        if fee_backup is not None:
            self.first_recorded_height = fee_backup.first_recorded_height
            self.latest_seen_height = fee_backup.latest_seen_height
            for stat in fee_backup.stats:
                if stat.type == "short":
                    self.short_horizon.import_backup(stat)
                if stat.type == "medium":
                    self.med_horizon.import_backup(stat)
                if stat.type == "long":
                    self.long_horizon.import_backup(stat)

    def shutdown(self) -> None:
        short = self.short_horizon.create_backup()
        medium = self.med_horizon.create_backup()
        long = self.long_horizon.create_backup()
        stats = [short, medium, long]
        backup = FeeTrackerBackup(
            uint8(FEE_ESTIMATOR_VERSION), self.first_recorded_height, self.latest_seen_height, stats
        )
        self.fee_store.store_fee_data(backup)

    def process_block(self, block_height: uint32, items: list[MempoolItemInfo]) -> None:
        """A new block has been farmed and these transactions have been included in that block"""
        if block_height <= self.latest_seen_height:
            # Ignore reorgs
            return

        self.latest_seen_height = block_height

        self.short_horizon.clear_current(block_height)
        self.med_horizon.clear_current(block_height)
        self.long_horizon.clear_current(block_height)

        self.short_horizon.update_moving_averages()
        self.med_horizon.update_moving_averages()
        self.long_horizon.update_moving_averages()

        for item in items:
            self.process_block_tx(block_height, item)

        if self.first_recorded_height == 0 and len(items) > 0:
            self.first_recorded_height = block_height
            self.log.info(f"Fee Estimator first recorded height: {self.first_recorded_height}")

    def process_block_tx(self, current_height: uint32, item: MempoolItemInfo) -> None:
        if item.height_added_to_mempool is None:
            raise ValueError("process_block_tx called with item.height_added_to_mempool=None")

        blocks_to_confirm = current_height - item.height_added_to_mempool
        if blocks_to_confirm <= 0:
            return

        self.short_horizon.tx_confirmed(blocks_to_confirm, item)
        self.med_horizon.tx_confirmed(blocks_to_confirm, item)
        self.long_horizon.tx_confirmed(blocks_to_confirm, item)

    def add_tx(self, item: MempoolItemInfo) -> None:
        if item.height_added_to_mempool < self.latest_seen_height:
            self.log.info(f"Processing Item from pending pool: cost={item.cost} fee={item.fee}")

        fee_rate = item.fee_per_cost * 1000
        bucket_index: int = get_bucket_index(self.buckets, fee_rate)

        self.short_horizon.new_mempool_tx(self.latest_seen_height, bucket_index)
        self.med_horizon.new_mempool_tx(self.latest_seen_height, bucket_index)
        self.long_horizon.new_mempool_tx(self.latest_seen_height, bucket_index)

    def remove_tx(self, item: MempoolItemInfo) -> None:
        bucket_index = get_bucket_index(self.buckets, item.fee_per_cost * 1000)
        self.short_horizon.remove_tx(self.latest_seen_height, item, bucket_index)
        self.med_horizon.remove_tx(self.latest_seen_height, item, bucket_index)
        self.long_horizon.remove_tx(self.latest_seen_height, item, bucket_index)

    def estimate_fee_for_block(self, target_block: uint32) -> EstimateResult:
        return self.med_horizon.estimate_median_val(
            conf_target=target_block,
            sufficient_tx_val=SUFFICIENT_FEE_TXS,
            success_break_point=SUCCESS_PCT,
            block_height=self.latest_seen_height,
        )

    def estimate_fee(self, target_time: int) -> EstimateResult:
        confirm_target_block = int(target_time / SECONDS_PER_BLOCK) + 1
        return self.estimate_fee_for_block(uint32(confirm_target_block))

    def estimate_fees(self) -> tuple[EstimateResult, EstimateResult, EstimateResult]:
        """returns the fee estimate for short, medium, and long time horizons"""
        short = self.short_horizon.estimate_median_val(
            conf_target=SHORT_BLOCK_PERIOD * SHORT_SCALE - SHORT_SCALE,
            sufficient_tx_val=SUFFICIENT_FEE_TXS,
            success_break_point=SUCCESS_PCT,
            block_height=self.latest_seen_height,
        )
        med = self.med_horizon.estimate_median_val(
            conf_target=MED_BLOCK_PERIOD * MED_SCALE - MED_SCALE,
            sufficient_tx_val=SUFFICIENT_FEE_TXS,
            success_break_point=SUCCESS_PCT,
            block_height=self.latest_seen_height,
        )
        long = self.long_horizon.estimate_median_val(
            conf_target=LONG_BLOCK_PERIOD * LONG_SCALE - LONG_SCALE,
            sufficient_tx_val=SUFFICIENT_FEE_TXS,
            success_break_point=SUCCESS_PCT,
            block_height=self.latest_seen_height,
        )

        return short, med, long
