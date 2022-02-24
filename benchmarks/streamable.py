from dataclasses import dataclass
from enum import Enum
from statistics import stdev
from time import process_time as clock
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union

import click
from utils import EnumType, rand_bytes, rand_full_block, rand_hash

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.util.ints import uint8, uint64
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class BenchmarkInner(Streamable):
    a: str


@dataclass(frozen=True)
@streamable
class BenchmarkMiddle(Streamable):
    a: uint64
    b: List[bytes32]
    c: Tuple[str, bool, uint8, List[bytes]]
    d: Tuple[BenchmarkInner, BenchmarkInner]
    e: BenchmarkInner


@dataclass(frozen=True)
@streamable
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
    mode = "{0:<10}".format(f"{mode}")
    us_per_iteration = "{0:<12}".format(f"{us_per_iteration}")
    stdev_us_per_iteration = "{0:>20}".format(f"{stdev_us_per_iteration}")
    avg_iterations = "{0:>18}".format(f"{avg_iterations}")
    stdev_iterations = "{0:>22}".format(f"{stdev_iterations}")
    print(f"{mode} | {us_per_iteration} | {stdev_us_per_iteration} | {avg_iterations} | {stdev_iterations}", end=end)


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


@click.command()
@click.option("-d", "--data", default=Data.all, type=EnumType(Data))
@click.option("-m", "--mode", default=Mode.all, type=EnumType(Mode))
@click.option("-r", "--runs", default=100, help="Number of benchmark runs to average results")
@click.option("-t", "--ms", default=50, help="Milliseconds per run")
@click.option("--live/--no-live", default=False, help="Print live results (slower)")
def run(data: Data, mode: Mode, runs: int, ms: int, live: bool) -> None:
    results: Dict[Data, Dict[Mode, List[List[int]]]] = {}
    for current_data, parameter in benchmark_parameter.items():
        results[current_data] = {}
        if data == Data.all or current_data == data:
            print(f"\nruns: {runs}, ms/run: {ms}, benchmarks: {mode.name}, data: {parameter.data_class.__name__}")
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

                    def print_results(print_run: int, final: bool) -> None:
                        all_runtimes: List[int] = [x for inner in all_results for x in inner]
                        total_iterations: int = len(all_runtimes)
                        total_elapsed_us: int = sum(all_runtimes)
                        avg_iterations: float = total_iterations / print_run
                        stdev_iterations: float = calc_stdev_percent([len(x) for x in all_results], avg_iterations)
                        stdev_us_per_iteration: float = calc_stdev_percent(
                            all_runtimes, total_elapsed_us / total_iterations
                        )
                        print_row(
                            mode=current_mode.name,
                            us_per_iteration=int(total_elapsed_us / total_iterations * 100) / 100,
                            stdev_us_per_iteration=stdev_us_per_iteration,
                            avg_iterations=int(avg_iterations),
                            stdev_iterations=stdev_iterations,
                            end="\n" if final else "\r",
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
                            print_results(current_run, False)
                    assert current_run == runs
                    print_results(runs, True)


if __name__ == "__main__":
    run()  # pylint: disable = no-value-for-parameter
