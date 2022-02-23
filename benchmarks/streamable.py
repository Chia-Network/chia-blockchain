from dataclasses import dataclass
from enum import Enum
from statistics import mean, stdev
from time import monotonic
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union

import click
from utils import rand_bytes, rand_full_block, rand_hash

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
    runs: Union[str, int],
    ms_per_run: Union[str, int],
    ns_per_iteration: Union[str, int],
    mode: str,
    avg_iterations: Union[str, int],
    stdev_iterations: Union[str, float],
    end: str = "\n",
) -> None:
    runs = "{0:<10}".format(f"{runs}")
    ms_per_run = "{0:<10}".format(f"{ms_per_run}")
    ns_per_iteration = "{0:<12}".format(f"{ns_per_iteration}")
    mode = "{0:<10}".format(f"{mode}")
    avg_iterations = "{0:>14}".format(f"{avg_iterations}")
    stdev_iterations = "{0:>13}".format(f"{stdev_iterations}")
    print(f"{runs} | {ms_per_run} | {ns_per_iteration} | {mode} | {avg_iterations} | {stdev_iterations}", end=end)


def benchmark_object_creation(iterations: int, class_generator: Callable[[], Any]) -> float:
    start = monotonic()
    obj = class_generator()
    cls = type(obj)
    for i in range(iterations):
        cls(**obj.__dict__)
    return monotonic() - start


def benchmark_conversion(
    iterations: int,
    class_generator: Callable[[], Any],
    conversion_cb: Callable[[Any], Any],
    preparation_cb: Optional[Callable[[Any], Any]] = None,
) -> float:
    obj = class_generator()
    start = monotonic()
    prepared_data = obj
    if preparation_cb is not None:
        prepared_data = preparation_cb(obj)
    for i in range(iterations):
        conversion_cb(prepared_data)
    return monotonic() - start


class Data(Enum):
    all = 0
    benchmark = 1
    full_block = 2


class Mode(Enum):
    all = 0
    creation = 1
    to_bytes = 2
    from_bytes = 3
    to_json = 4
    from_json = 5


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
    ns_iteration_results: List[int] = []
    start = monotonic()
    while int((monotonic() - start) * 1000) < ms_to_run:
        start_iteration = monotonic()
        cb()
        stop_iteration = monotonic()
        ns_iteration_results.append(int((stop_iteration - start_iteration) * 1000 * 1000))
    return ns_iteration_results


def calc_stdev(iterations: List[int]) -> float:
    return 0 if len(iterations) < 2 else int(stdev(iterations) * 100) / 100


def run_benchmarks(data: Data, mode: Mode, runs: int, milliseconds: int) -> None:
    results: Dict[Data, Dict[Mode, List[List[int]]]] = {}
    for current_data, parameter in benchmark_parameter.items():
        results[current_data] = {}
        if data == Data.all or current_data == data:
            print(f"\nRun {mode.name} benchmarks with the class: {parameter.data_class.__name__}")
            print_row(
                runs="runs",
                ms_per_run="ms/run",
                ns_per_iteration="ns/iteration",
                mode="mode",
                avg_iterations="avg iterations",
                stdev_iterations="stdev iterations",
            )
            for current_mode, current_mode_parameter in parameter.mode_parameter.items():
                results[current_data][current_mode] = []
                if mode == Mode.all or current_mode == mode:
                    ns_iteration_results: List[int]
                    all_results: List[List[int]] = results[current_data][current_mode]
                    obj = parameter.object_creation_cb()

                    def print_results(print_run: int, final: bool) -> None:
                        total_iterations: int = sum(len(x) for x in all_results)
                        total_elapsed_ns: int = sum(sum(x) for x in all_results)
                        print_row(
                            runs=print_run if final else "current",
                            ms_per_run=int(mean(sum(x) for x in all_results) / 1000),
                            ns_per_iteration=int(total_elapsed_ns / total_iterations),
                            mode=current_mode.name,
                            avg_iterations=int(total_iterations / print_run),
                            stdev_iterations=calc_stdev([len(x) for x in all_results]),
                            end="\n" if final else "\r",
                        )

                    current_run: int = 0
                    while current_run < runs:
                        current_run += 1

                        if current_mode == Mode.creation:
                            cls = type(obj)
                            ns_iteration_results = run_for_ms(lambda: cls(**obj.__dict__), milliseconds)
                        else:
                            assert current_mode_parameter is not None
                            conversion_cb = current_mode_parameter.conversion_cb
                            assert conversion_cb is not None
                            prepared_obj = parameter.object_creation_cb()
                            if current_mode_parameter.preparation_cb is not None:
                                prepared_obj = current_mode_parameter.preparation_cb(obj)
                            ns_iteration_results = run_for_ms(lambda: conversion_cb(prepared_obj), milliseconds)
                        all_results.append(ns_iteration_results)
                        print_results(current_run, False)
                    assert current_run == runs
                    print_results(runs, True)


data_option_help: str = "|".join([d.name for d in Data])
mode_option_help: str = "|".join([m.name for m in Mode])


@click.command()
@click.option("-d", "--data", default=Data.all.name, help=data_option_help)
@click.option("-m", "--mode", default=Mode.all.name, help=mode_option_help)
@click.option("-r", "--runs", default=100, help="Number of benchmark runs to average results")
@click.option("-t", "--ms", default=50, help="Milliseconds per run")
def run(data: str, mode: str, runs: int, ms: int) -> None:
    try:
        Data[data]
    except Exception:
        raise click.BadOptionUsage("data", f"{data} is not a valid data option. Select one from: " + data_option_help)
    try:
        Mode[mode]
    except Exception:
        raise click.BadOptionUsage("mode", f"{mode} is not a valid mode option. Select one from: " + mode_option_help)
    run_benchmarks(Data[data], Mode[mode], max(1, runs), ms)


if __name__ == "__main__":
    run()  # pylint: disable = no-value-for-parameter
