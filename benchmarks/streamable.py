from dataclasses import dataclass
from enum import Enum
from statistics import stdev
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
    runs: Union[str, int],
    iterations: Union[str, int],
    mode: str,
    duration: Union[str, int],
    std_deviation: Union[str, float],
    end: str = "\n",
) -> None:
    runs = "{0:<10}".format(f"{runs}")
    iterations = "{0:<10}".format(f"{iterations}")
    mode = "{0:<10}".format(f"{mode}")
    duration = "{0:>14}".format(f"{duration}")
    std_deviation = "{0:>13}".format(f"{std_deviation}")
    print(f"{runs} | {iterations} | {mode} | {duration} | {std_deviation}", end=end)


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


def run_for_ms(cb: Callable[[], Any], ms_to_run: int = 100) -> int:
    iterations: int = 0
    start = monotonic()
    while int((monotonic() - start) * 1000) < ms_to_run:
        cb()
        iterations += 1
    return iterations


def calc_stdev(iterations: List[int]) -> float:
    return 0 if len(iterations) < 2 else int(stdev(iterations) * 100) / 100


def run_benchmarks(data: Data, mode: Mode, runs: int, milliseconds: int) -> None:
    results: Dict[Data, Dict[Mode, List[int]]] = {}
    for current_data, parameter in benchmark_parameter.items():
        results[current_data] = {}
        if data == Data.all or current_data == data:
            print(f"\nRun {mode.name} benchmarks with the class: {parameter.data_class.__name__}")
            print_row("runs", "ms/run", "mode", "avg iterations", "std deviation")
            for current_mode, current_mode_parameter in parameter.mode_parameter.items():
                results[current_data][current_mode] = []
                if mode == Mode.all or current_mode == mode:
                    iterations: int
                    all_iterations: List[int] = results[current_data][current_mode]
                    for _ in range(max(1, runs)):
                        obj = parameter.object_creation_cb()
                        if current_mode == Mode.creation:
                            cls = type(obj)
                            iterations = run_for_ms(lambda: cls(**obj.__dict__), milliseconds)
                        else:
                            assert current_mode_parameter is not None
                            conversion_cb = current_mode_parameter.conversion_cb
                            assert conversion_cb is not None
                            if current_mode_parameter.preparation_cb is not None:
                                obj = current_mode_parameter.preparation_cb(obj)
                            iterations = run_for_ms(lambda: conversion_cb(obj), milliseconds)
                        all_iterations.append(iterations)
                        print_row("last", milliseconds, current_mode.name, iterations, calc_stdev(all_iterations), "\r")
                    average_iterations: int = int(sum(all_iterations) / runs)
                    print_row(runs, milliseconds, current_mode.name, average_iterations, calc_stdev(all_iterations))


data_option_help: str = "|".join([d.name for d in Data])
mode_option_help: str = "|".join([m.name for m in Mode])


@click.command()
@click.option("-d", "--data", default=Data.all.name, help=data_option_help)
@click.option("-m", "--mode", default=Mode.all.name, help=mode_option_help)
@click.option("-r", "--runs", default=50, help="Number of benchmark runs to average results")
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
    run_benchmarks(Data[data], Mode[mode], runs, ms)


if __name__ == "__main__":
    run()  # pylint: disable = no-value-for-parameter
