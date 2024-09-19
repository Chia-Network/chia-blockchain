from __future__ import annotations

import itertools
import random
import time
from typing import Any, Dict, List

import big_o
import big_o.complexities
import pytest

from chia._tests.util.misc import BenchmarkRunner
from chia.data_layer.data_layer_util import Status
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.sized_bytes import bytes32


def generate_changelist(r: random.Random, size: int) -> List[Dict[str, Any]]:
    return [
        {
            "action": "insert",
            "key": x.to_bytes(32, byteorder="big", signed=False),
            "value": bytes(r.getrandbits(8) for _ in range(1200)),
        }
        for x in range(size)
    ]


def process_big_o(lowest_considered_n: int, records: Dict[int, float], simplicity_bias_percentage) -> None:
    __tracebackhide__ = True

    considered_durations = {n: duration for n, duration in records.items() if n >= lowest_considered_n}
    ns = list(considered_durations.keys())
    durations = list(considered_durations.values())
    best_class, fitted = big_o.infer_big_o_class(ns=ns, time=durations)
    simplicity_bias = simplicity_bias_percentage * fitted[best_class]
    best_class, fitted = big_o.infer_big_o_class(ns=ns, time=durations, simplicity_bias=simplicity_bias)
    print(f"allowed simplicity bias: {simplicity_bias}")
    print(big_o.reports.big_o_report(best=best_class, others=fitted))
    assert isinstance(
        best_class, (big_o.complexities.Constant, big_o.complexities.Linear)
    ), f"must be constant or linear: {best_class}"
    coefficient_maximums = [0.65, 0.000_25, *(10**-n for n in range(5, 100))]
    coefficients = best_class.coefficients()
    paired = list(zip(coefficients, coefficient_maximums))
    assert len(paired) == len(coefficients)
    for index, [actual, maximum] in enumerate(paired):
        assert actual <= maximum, f"(coefficient {index}) {actual} > {maximum}: {paired}"


@pytest.mark.anyio
async def test_benchmark_batch_insert_speed(
    data_store: DataStore,
    store_id: bytes32,
    benchmark_runner: BenchmarkRunner,
) -> None:
    r = random.Random()
    r.seed("shadowlands", version=2)

    test_size = 100
    step_size = 100
    assert step_size >= test_size
    max_pre_size = 20_000
    # may not be needed if big_o already considers the effect
    # TODO: must be > 0 to avoid an issue with the log class?
    lowest_considered_n = 500

    batch_count, remainder = divmod(max_pre_size, test_size)
    assert remainder == 0, "the last batch would be a different size"

    records: Dict[int, float] = {}

    total_inserted = 0
    changelist_iter = iter(generate_changelist(r=r, size=max_pre_size))
    with benchmark_runner.print_runtime(
        label="overall",
        clock=time.monotonic,
    ):
        while True:
            batch = list(itertools.islice(changelist_iter, test_size))
            if len(batch) == 0:
                break

            with benchmark_runner.print_runtime(
                label="count",
                clock=time.monotonic,
            ) as f:
                await data_store.insert_batch(
                    store_id=store_id,
                    changelist=batch,
                    # TODO: does this mess up test accuracy?
                    status=Status.COMMITTED,
                )

            records[total_inserted] = f.result().duration
            total_inserted += len(batch)

            step_batch = list(itertools.islice(changelist_iter, step_size - test_size))
            if len(step_batch) > 0:
                await data_store.insert_batch(
                    store_id=store_id,
                    changelist=step_batch,
                    # TODO: does this mess up test accuracy?
                    status=Status.COMMITTED,
                )
                total_inserted += len(step_batch)

    process_big_o(
        lowest_considered_n=lowest_considered_n,
        records=records,
        simplicity_bias_percentage=10 / 100,
    )

    assert False, "actually passing but this forces output"


@pytest.mark.anyio
async def test_benchmark_insert_node_speed(
    data_store: DataStore,
    store_id: bytes32,
    benchmark_runner: BenchmarkRunner,
) -> None:
    r = random.Random()
    r.seed("shadowlands", version=2)

    test_size = 100
    step_size = 100
    assert step_size >= test_size
    max_pre_size = 20_000
    # may not be needed if big_o already considers the effect
    # TODO: must be > 0 to avoid an issue with the log class?
    lowest_considered_n = 500

    batch_count, remainder = divmod(max_pre_size, test_size)
    assert remainder == 0, "the last batch would be a different size"

    records: Dict[int, float] = {}

    total_inserted = 0
    changelist_iter = iter(generate_changelist(r=r, size=max_pre_size))
    with benchmark_runner.print_runtime(
        label="overall",
        clock=time.monotonic,
    ):
        while True:
            batch = list(itertools.islice(changelist_iter, test_size))
            if len(batch) == 0:
                break

            with benchmark_runner.print_runtime(
                label="count",
                clock=time.monotonic,
            ) as f:
                await data_store.insert_batch(
                    store_id=store_id,
                    changelist=batch,
                    # TODO: does this mess up test accuracy?
                    status=Status.COMMITTED,
                )

            records[total_inserted] = f.result().duration
            total_inserted += len(batch)

            step_batch = list(itertools.islice(changelist_iter, step_size - test_size))
            if len(step_batch) > 0:
                await data_store.insert_batch(
                    store_id=store_id,
                    changelist=step_batch,
                    # TODO: does this mess up test accuracy?
                    status=Status.COMMITTED,
                )
                total_inserted += len(step_batch)

    process_big_o(
        lowest_considered_n=lowest_considered_n,
        records=records,
        simplicity_bias_percentage=10 / 100,
    )

    assert False, "actually passing but this forces output"
