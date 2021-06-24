from typing import List
from sortedcontainers import SortedDict

from chia.full_node.fee_estimator_constants import (
    INFINITE_FEE_RATE,
    STEP_SIZE,
    LONG_SCALE,
    MED_SCALE,
    SHORT_SCALE,
    SHORT_BLOCK_PERIODS,
    MED_BLOCK_PERIODS,
    LONG_BLOCK_PERIODS,
    SUFFICIENT_FEETXS,
    SUCCESS_PCT,
    LONG_DECAY,
    MED_DECAY,
    SHORT_DECAY,
    INITIAL_STEP,
    MAX_FEE_RATE,
)
from chia.types.mempool_item import MempoolItem


# Implementation of bitcoin core fee estimation algorithm
# https://gist.github.com/morcos/d3637f015bc4e607e1fd10d8351e9f41
class FeeStat:
    buckets: List[float]
    sorted_buckets: SortedDict  # keys is upper bound of bucket, val is index in buckets

    # Fot each bucket xL
    # Count the total number of txs in each bucket
    # Track historical moving average of this total over block
    tx_ct_avg: List[float]

    # Count the total number of txs confirmed within Y blocks in each bucket
    # Track the historical moving average of these totals over blocks
    confirmed_average: List[List[float]]  # confirmed_average [y][x]

    # Track moving average of txs which have been evicted from the mempool
    # after failing to be confirmed within Y block
    failed_average: List[List[float]]  # failed_average [y][x]

    # Sum the total feerate of all txs in each bucket
    # Track historical moving averate of this total over blocks
    m_feerate_avg: List[float]

    decay: float

    # Resolution of blocks with which confirmations are tracked
    scale: int

    # Mempool counts of outstanding transactions
    # For each bucket x, track the number of transactions in mempool
    # that are unconfirmed for each possible confirmation value y
    unconfirmed_txs: List[List[int]]
    # transactions still unconfirmed after get_max_confirmes for each bucket
    old_unconf_txs: List[int]
    max_confirms: int

    def __init__(self, buckets, sorted_buckets, max_periods, decay, scale, log):
        self.buckets = buckets
        self.sorted_buckets = sorted_buckets
        self.confirmed_average = [[] for _ in range(0, max_periods)]
        self.failed_average = [[] for _ in range(0, max_periods)]
        self.decay = decay
        self.scale = scale
        self.max_confirms = self.scale * len(self.confirmed_average)
        self.log = log

        for i in range(0, max_periods):
            self.confirmed_average[i] = [0 for _ in range(0, len(buckets))]
            self.failed_average[i] = [0 for _ in range(0, len(buckets))]

        self.tx_ct_avg = [0 for _ in range(0, len(buckets))]
        self.m_feerate_avg = [0 for _ in range(0, len(buckets))]

        self.unconfirmed_txs = [[] for _ in range(0, self.max_confirms)]
        for i in range(0, self.max_confirms):
            self.unconfirmed_txs[i] = [0 for _ in range(0, len(buckets))]

        self.old_unconf_txs = [0 for _ in range(0, len(buckets))]

    def get_bucket_index(self, feerate) -> int:
        if feerate in self.sorted_buckets:
            bucket_index = self.sorted_buckets[feerate]
        else:
            bucket_index = self.sorted_buckets.bisect_left(feerate) - 1

        return bucket_index

    def tx_confirmed(self, blocks_to_confirm: int, item: MempoolItem):
        if blocks_to_confirm < 1:
            return

        periods_to_confirm = int((blocks_to_confirm + self.scale - 1) / self.scale)

        feerate = item.fee_per_k_cost
        bucket_index = self.get_bucket_index(feerate)

        for i in range(periods_to_confirm, len(self.confirmed_average)):
            self.confirmed_average[i - 1][bucket_index] += 1

        self.tx_ct_avg[bucket_index] += 1
        self.m_feerate_avg[bucket_index] += feerate

    def update_moving_averages(self):
        for j in range(0, len(self.buckets)):
            for i in range(0, len(self.confirmed_average)):
                self.confirmed_average[i][j] *= self.decay
                self.failed_average[i][j] *= self.decay

            self.tx_ct_avg[j] *= self.decay
            self.m_feerate_avg[j] *= self.decay

    def clear_current(self, block_height):
        for i in range(0, len(self.buckets)):
            self.old_unconf_txs[i] += self.unconfirmed_txs[block_height % len(self.unconfirmed_txs)][i]
            self.unconfirmed_txs[block_height % len(self.unconfirmed_txs)][i] = 0

    def new_mempool_tx(self, block_height, fee_rate):
        bucket_index = self.get_bucket_index(fee_rate)
        block_index = block_height % len(self.unconfirmed_txs)
        self.unconfirmed_txs[block_index][bucket_index] += 1
        return bucket_index

    def remove_tx(self, latest_seen_height, item: MempoolItem, bucket_index):
        if item.height_added is None:
            return
        block_ago = latest_seen_height - item.height_added
        if latest_seen_height == 0:
            block_ago = 0

        if block_ago < 0:
            return

        if block_ago >= len(self.unconfirmed_txs):
            if self.old_unconf_txs[bucket_index] > 0:
                self.old_unconf_txs[bucket_index] -= 1
            else:
                self.log.warning("Fee estimator error")
        else:
            block_index = item.height_added % len(self.unconfirmed_txs)
            if self.unconfirmed_txs[block_index][bucket_index] > 0:
                self.unconfirmed_txs[block_index][bucket_index] -= 1
            else:
                self.log.warning("Fee estimator error")

        if block_ago >= self.scale:
            periods_ago = block_ago / self.scale
            for i in range(0, len(self.failed_average)):
                if i >= periods_ago:
                    break
                self.failed_average[i][bucket_index] += 1

    def estimate_median_val(self, conf_target: int, sufficient_tx_val: float, success_break_point: float, block_height):
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
        pass_bucket = {}
        fail_bucket = {}
        for bucket in range(max_bucket_index, -1, -1):
            if new_bucket_range:
                cur_near_bucket = bucket
                new_bucket_range = False

            cur_far_bucket = bucket
            n_conf += self.confirmed_average[period_target - 1][bucket]
            total_num += self.tx_ct_avg[bucket]
            fail_num += self.failed_average[period_target - 1][bucket]
            for conf_ct in range(conf_target, self.max_confirms):
                extra_num += self.unconfirmed_txs[(block_height - conf_ct) % bins][bucket]
            extra_num += self.old_unconf_txs[bucket]

            if total_num >= sufficient_tx_val / (1 - self.decay):
                curr_pct = n_conf / (total_num + fail_num + extra_num)

                # Check to see if we are no longer getting confirmed at the same rate
                if curr_pct < success_break_point:
                    if passing is True:
                        fail_min_bucket = min(cur_near_bucket, cur_far_bucket)
                        fail_max_bucket = max(cur_near_bucket, cur_far_bucket)
                        fail_bucket["start"] = self.buckets[fail_min_bucket - 1] if fail_min_bucket else 0
                        fail_bucket["end"] = self.buckets[fail_max_bucket]
                        fail_bucket["within_target"] = n_conf
                        fail_bucket["total_confirmed"] = total_num
                        fail_bucket["in_mempool"] = extra_num
                        fail_bucket["left_mempool"] = fail_num
                        passing = False
                    continue
                else:
                    fail_bucket = {}
                    found_answer = True
                    passing = True
                    pass_bucket["within_target"] = n_conf
                    n_conf = 0
                    pass_bucket["total_confirmed"] = total_num
                    total_num = 0
                    pass_bucket["in_mempool"] = extra_num
                    pass_bucket["left_mempool"] = fail_num
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
            tx_sum = tx_sum / 2
            for i in range(min_bucket, max_bucket):
                if self.tx_ct_avg[i] < tx_sum:
                    tx_sum -= self.tx_ct_avg[i]
                else:
                    median = self.m_feerate_avg[i] / self.tx_ct_avg[i]
                    break
            pass_bucket["start"] = self.buckets[min_bucket - 1] if min_bucket else 0
            pass_bucket["end"] = self.buckets[max_bucket]

        if passing and new_bucket_range is False:
            fail_min_bucket = min(cur_near_bucket, cur_far_bucket)
            fail_max_bucket = max(cur_near_bucket, cur_far_bucket)
            fail_bucket["start"] = self.buckets[fail_min_bucket - 1] if fail_min_bucket else 0
            fail_bucket["end"] = self.buckets[fail_max_bucket]
            fail_bucket["within_target"] = n_conf
            fail_bucket["total_confirmed"] = total_num
            fail_bucket["in_mempool"] = extra_num
            fail_bucket["left_mempool"] = fail_num

        passed_within_target_perc = 0.0
        failed_within_target_perc = 0.0
        if (
            "total_confirmed" in pass_bucket
            and pass_bucket["total_confirmed"] + pass_bucket["in_mempool"] + pass_bucket["left_mempool"] > 0
        ):
            passed_within_target_perc = (
                100 * pass_bucket["within_target"] / pass_bucket["total_confirmed"]
                + pass_bucket["in_mempool"]
                + pass_bucket["left_mempool"]
            )
        if (
            "total_confirmed" in fail_bucket
            and fail_bucket["total_confirmed"] + fail_bucket["in_mempool"] + fail_bucket["left_mempool"] > 0
        ):
            failed_within_target_perc = (
                100 * fail_bucket["within_target"] / fail_bucket["total_confirmed"]
                + fail_bucket["in_mempool"]
                + fail_bucket["left_mempool"]
            )

        self.log.info(f"passed_within_target_perc: {passed_within_target_perc}")
        self.log.info(f"failed_within_target_perc: {failed_within_target_perc}")

        return pass_bucket, fail_bucket, median


class FeeTracker:
    def __init__(self, log):
        self.log = log
        self.sorted_buckets: SortedDict = SortedDict()
        self.buckets = []
        self.latest_seen_height = 0
        self.first_recorded_height = 0
        self.historical_first = 0
        self.historical_best = 0
        self.tracked_txs = 0
        self.untracked_txs = 0
        fee_rate = 0
        index = 0

        while fee_rate < MAX_FEE_RATE:
            self.buckets.append(fee_rate)
            self.sorted_buckets[fee_rate] = index
            if fee_rate == 0:
                fee_rate = INITIAL_STEP
            else:
                fee_rate = fee_rate * STEP_SIZE
            index += 1
        self.buckets.append(INFINITE_FEE_RATE)
        self.sorted_buckets[INFINITE_FEE_RATE] = index

        assert len(self.sorted_buckets.keys()) == len(self.buckets)

        self.short_horizon = FeeStat(
            self.buckets, self.sorted_buckets, SHORT_BLOCK_PERIODS, SHORT_DECAY, SHORT_SCALE, self.log
        )
        self.med_horizon = FeeStat(self.buckets, self.sorted_buckets, MED_BLOCK_PERIODS, MED_DECAY, MED_SCALE, self.log)
        self.long_horizon = FeeStat(
            self.buckets, self.sorted_buckets, LONG_BLOCK_PERIODS, LONG_DECAY, LONG_SCALE, self.log
        )

    def process_block(self, block_height: int, items: List[MempoolItem]):
        """New block has been farmed and these transaction have been included"""
        if block_height <= self.latest_seen_height:
            # Ignore reorgs
            return

        self.latest_seen_height = block_height

        self.short_horizon.update_moving_averages()
        self.med_horizon.update_moving_averages()
        self.long_horizon.update_moving_averages()

        counted_txs = 0
        for item in items:
            counted_txs += 1
            self.process_block_tx(block_height, item)

        if self.first_recorded_height == 0 and counted_txs > 0:
            self.log.info("Fee Estimator first recorded height")
            self.first_recorded_height = block_height

    def process_block_tx(self, height, item: MempoolItem):
        if item.height_added is None:
            return

        blocks_to_confirm = height - item.height_added
        if blocks_to_confirm <= 0:
            return

        self.short_horizon.tx_confirmed(blocks_to_confirm, item)
        self.med_horizon.tx_confirmed(blocks_to_confirm, item)
        self.long_horizon.tx_confirmed(blocks_to_confirm, item)

    def get_bucket_index(self, feerate) -> int:
        if feerate in self.sorted_buckets:
            bucket_index = self.sorted_buckets[feerate]
        else:
            bucket_index = self.sorted_buckets.bisect_left(feerate) - 1

        return bucket_index

    def remove_tx(self, item: MempoolItem):
        bucket_index = self.get_bucket_index(item.fee_per_k_cost)
        self.short_horizon.remove_tx(self.latest_seen_height, item, bucket_index)
        self.med_horizon.remove_tx(self.latest_seen_height, item, bucket_index)
        self.long_horizon.remove_tx(self.latest_seen_height, item, bucket_index)

    def estimate_fee(self):
        """returns the fee estimate for short,medium, and long time horizon"""
        short = self.short_horizon.estimate_median_val(
            conf_target=SHORT_BLOCK_PERIODS * SHORT_SCALE - SHORT_SCALE,
            sufficient_tx_val=SUFFICIENT_FEETXS,
            success_break_point=SUCCESS_PCT,
            block_height=self.latest_seen_height,
        )
        med = self.med_horizon.estimate_median_val(
            conf_target=MED_BLOCK_PERIODS * MED_SCALE - MED_SCALE,
            sufficient_tx_val=SUFFICIENT_FEETXS,
            success_break_point=SUCCESS_PCT,
            block_height=self.latest_seen_height,
        )
        long = self.long_horizon.estimate_median_val(
            conf_target=LONG_BLOCK_PERIODS * LONG_SCALE - LONG_SCALE,
            sufficient_tx_val=SUFFICIENT_FEETXS,
            success_break_point=SUCCESS_PCT,
            block_height=self.latest_seen_height,
        )

        return short, med, long
