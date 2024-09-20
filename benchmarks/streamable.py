from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import Enum
from statistics import stdev
from time import process_time as clock
from typing import Any, Callable, Dict, List, Optional, TextIO, Tuple, Type, Union

import click

from benchmarks.utils import EnumType, get_commit_hash
from chia._tests.util.benchmarks import rand_bytes, rand_full_block, rand_hash
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.util.ints import uint8, uint64
from chia.util.streamable import Streamable, streamable

# to run this benchmark:
# python -m benchmarks.streamable

_version = 1


@streamable
@dataclass(frozen=True)
class BenchmarkInner(Streamable):
    a: str


@streamable
@dataclass(frozen=True)
class BenchmarkMiddle(Streamable):
    a: uint64
    b: List[bytes32]
    c: Tuple[str, bool, uint8, List[bytes]]
    d: Tuple[BenchmarkInner, BenchmarkInner]
    e: BenchmarkInner


@streamable
@dataclass(frozen=True)
class BenchmarkClass(Streamable):
    a: Optional[BenchmarkMiddle]
    b: Optional[BenchmarkMiddle]
    c: BenchmarkMiddle
    d: List[BenchmarkMiddle]
    e: Tuple[BenchmarkMiddle, BenchmarkMiddle, BenchmarkMiddle]


def get_random_inner() -> BenchmarkInner:
    return BenchmarkInner(rand_bytes(20).hex())


def get_random_middle() -> BenchmarkMiddle:
    a: uint64 = uint64(10)
    b: List[bytes32] = [rand_hash() for _ in range(a)]
    c: Tuple[str, bool, uint8, List[bytes]] = ("benchmark", False, uint8(1), [rand_bytes(a) for _ in range(a)])
    d: Tuple[BenchmarkInner, BenchmarkInner] = (get_random_inner(), get_random_inner())
    e: BenchmarkInner = get_random_inner()
    return BenchmarkMiddle(a, b, c, d, e)


def get_random_benchmark_object() -> BenchmarkClass:
    a: Optional[BenchmarkMiddle] = None
    b: Optional[BenchmarkMiddle] = get_random_middle()
    c: BenchmarkMiddle = get_random_middle()
    d: List[BenchmarkMiddle] = [get_random_middle() for _ in range(5)]
    e: Tuple[BenchmarkMiddle, BenchmarkMiddle, BenchmarkMiddle] = (
        get_random_middle(),
        get_random_middle(),
        get_random_middle(),
    )
    return BenchmarkClass(a, b, c, d, e)


def print_row(
    *,
    mode: str,
    us_per_iteration: Union[str, float],
    stdev_us_per_iteration: Union[str, float],
    avg_iterations: Union[str, int],
    stdev_iterations: Union[str, float],
    end: str = "\n",
) -> None:
    print(
        " | ".join(
            [
                f"{mode:<10}",
                f"{us_per_iteration:<12}",
                f"{stdev_us_per_iteration:>20}",
                f"{avg_iterations:>18}",
                f"{stdev_iterations:>22}",
            ]
        ),
        end=end,
    )


@dataclass
class BenchmarkResults:
    us_per_iteration: float
    stdev_us_per_iteration: float
    avg_iterations: int
    stdev_iterations: float


def print_results(mode: str, bench_result: BenchmarkResults, final: bool) -> None:
    print_row(
        mode=mode,
        us_per_iteration=bench_result.us_per_iteration,
        stdev_us_per_iteration=bench_result.stdev_us_per_iteration,
        avg_iterations=bench_result.avg_iterations,
        stdev_iterations=bench_result.stdev_iterations,
        end="\n" if final else "\r",
    )


# The strings in this Enum are by purpose. See benchmark.utils.EnumType.
class Data(str, Enum):
    all = "all"
    benchmark = "benchmark"
    full_block = "full_block"


# The strings in this Enum are by purpose. See benchmark.utils.EnumType.
class Mode(str, Enum):
    all = "all"
    creation = "creation"
    to_bytes = "to_bytes"
    from_bytes = "from_bytes"
    to_json = "to_json"
    from_json = "from_json"


def to_bytes(obj: Any) -> bytes:
    return bytes(obj)


@dataclass
class ModeParameter:
    conversion_cb: Callable[[Any], Any]
    preparation_cb: Optional[Callable[[Any], Any]] = None


@dataclass
class BenchmarkParameter:
    data_class: Type[Any]
    object_creation_cb: Callable[[], Any]
    mode_parameter: Dict[Mode, Optional[ModeParameter]]


benchmark_parameter: Dict[Data, BenchmarkParameter] = {
    Data.benchmark: BenchmarkParameter(
        BenchmarkClass,
        get_random_benchmark_object,
        {
            Mode.creation: None,
            Mode.to_bytes: ModeParameter(to_bytes),
            Mode.from_bytes: ModeParameter(BenchmarkClass.from_bytes, to_bytes),
            Mode.to_json: ModeParameter(BenchmarkClass.to_json_dict),
            Mode.from_json: ModeParameter(BenchmarkClass.from_json_dict, BenchmarkClass.to_json_dict),
        },
    ),
    Data.full_block: BenchmarkParameter(
        FullBlock,
        rand_full_block,
        {
            Mode.creation: None,
            Mode.to_bytes: ModeParameter(to_bytes),
            Mode.from_bytes: ModeParameter(FullBlock.from_bytes, to_bytes),
            Mode.to_json: ModeParameter(FullBlock.to_json_dict),
            Mode.from_json: ModeParameter(FullBlock.from_json_dict, FullBlock.to_json_dict),
        },
    ),
}


def run_for_ms(cb: Callable[[], Any], ms_to_run: int = 100) -> List[int]:
    us_iteration_results: List[int] = []
    start = clock()
    while int((clock() - start) * 1000) < ms_to_run:
        start_iteration = clock()
        cb()
        stop_iteration = clock()
        us_iteration_results.append(int((stop_iteration - start_iteration) * 1000 * 1000))
    return us_iteration_results


def calc_stdev_percent(iterations: List[int], avg: float) -> float:
    deviation = 0 if len(iterations) < 2 else int(stdev(iterations) * 100) / 100
    return int((deviation / avg * 100) * 100) / 100


def pop_data(key: str, *, old: Dict[str, Any], new: Dict[str, Any]) -> Tuple[Any, Any]:
    if key not in old:
        sys.exit(f"{key} missing in old")
    if key not in new:
        sys.exit(f"{key} missing in new")
    return old.pop(key), new.pop(key)


def print_compare_row(c0: str, c1: Union[str, float], c2: Union[str, float], c3: Union[str, float]) -> None:
    print(f"{c0:<12} | {c1:<16} | {c2:<16} | {c3:<12}")


def compare_results(
    old: Dict[str, Dict[str, Dict[str, Union[float, int]]]], new: Dict[str, Dict[str, Dict[str, Union[float, int]]]]
) -> None:
    old_version, new_version = pop_data("version", old=old, new=new)
    if old_version != new_version:
        sys.exit(f"version mismatch: old: {old_version} vs new: {new_version}")
    old_commit_hash, new_commit_hash = pop_data("commit_hash", old=old, new=new)
    for data, modes in new.items():
        if data not in old:
            continue
        print(f"\ncompare: {data}, old: {old_commit_hash}, new: {new_commit_hash}")
        print_compare_row("mode", "µs/iteration old", "µs/iteration new", "diff %")
        for mode, results in modes.items():
            if mode not in old[data]:
                continue
            old_us, new_us = pop_data("us_per_iteration", old=old[data][mode], new=results)
            print_compare_row(mode, old_us, new_us, int((new_us - old_us) / old_us * 10000) / 100)


@click.command()
@click.option("-d", "--data", default=Data.all, type=EnumType(Data))
@click.option("-m", "--mode", default=Mode.all, type=EnumType(Mode))
@click.option("-r", "--runs", default=100, help="Number of benchmark runs to average results")
@click.option("-t", "--ms", default=50, help="Milliseconds per run")
@click.option("--live/--no-live", default=False, help="Print live results (slower)")
@click.option("-o", "--output", type=click.File("w"), help="Write the results to a file")
@click.option("-c", "--compare", type=click.File("r"), help="Compare to the results from a file")
def run(data: Data, mode: Mode, runs: int, ms: int, live: bool, output: TextIO, compare: TextIO) -> None:
    results: Dict[Data, Dict[Mode, List[List[int]]]] = {}
    bench_results: Dict[str, Any] = {"version": _version, "commit_hash": get_commit_hash()}
    for current_data, parameter in benchmark_parameter.items():
        if data == Data.all or current_data == data:
            results[current_data] = {}
            bench_results[current_data] = {}
            print(
                f"\nbenchmarks: {mode.name}, data: {parameter.data_class.__name__} runs: {runs}, ms/run: {ms}, "
                f"commit_hash: {bench_results['commit_hash']}"
            )
            print_row(
                mode="mode",
                us_per_iteration="µs/iteration",
                stdev_us_per_iteration="stdev µs/iteration %",
                avg_iterations="avg iterations/run",
                stdev_iterations="stdev iterations/run %",
            )
            for current_mode, current_mode_parameter in parameter.mode_parameter.items():
                results[current_data][current_mode] = []
                if mode == Mode.all or current_mode == mode:
                    us_iteration_results: List[int]
                    all_results: List[List[int]] = results[current_data][current_mode]
                    obj = parameter.object_creation_cb()

                    def get_bench_results() -> BenchmarkResults:
                        all_runtimes: List[int] = [x for inner in all_results for x in inner]
                        total_iterations: int = len(all_runtimes)
                        total_elapsed_us: int = sum(all_runtimes)
                        avg_iterations: float = total_iterations / len(all_results)
                        stdev_iterations: float = calc_stdev_percent([len(x) for x in all_results], avg_iterations)
                        us_per_iteration: float = total_elapsed_us / total_iterations
                        stdev_us_per_iteration: float = calc_stdev_percent(
                            all_runtimes, total_elapsed_us / total_iterations
                        )
                        return BenchmarkResults(
                            int(us_per_iteration * 100) / 100,
                            stdev_us_per_iteration,
                            int(avg_iterations),
                            stdev_iterations,
                        )

                    current_run: int = 0
                    while current_run < runs:
                        current_run += 1

                        if current_mode == Mode.creation:
                            cls = type(obj)
                            us_iteration_results = run_for_ms(lambda: cls(**obj.__dict__), ms)
                        else:
                            assert current_mode_parameter is not None
                            conversion_cb = current_mode_parameter.conversion_cb
                            assert conversion_cb is not None
                            prepared_obj = parameter.object_creation_cb()
                            if current_mode_parameter.preparation_cb is not None:
                                prepared_obj = current_mode_parameter.preparation_cb(obj)
                            us_iteration_results = run_for_ms(lambda: conversion_cb(prepared_obj), ms)
                        all_results.append(us_iteration_results)
                        if live:
                            print_results(current_mode.name, get_bench_results(), False)
                    assert current_run == runs
                    bench_result = get_bench_results()
                    bench_results[current_data][current_mode] = bench_result.__dict__
                    print_results(current_mode.name, bench_result, True)
    json_output = json.dumps(bench_results)
    if output:
        output.write(json_output)
    if compare:
        compare_results(json.load(compare), json.loads(json_output))


if __name__ == "__main__":
    run()  # pylint: disable = no-value-for-parameter
