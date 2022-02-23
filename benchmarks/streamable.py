from dataclasses import dataclass
from enum import Enum
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
    runs: Union[str, int], iterations: Union[str, int], mode: str, duration: Union[str, int], end: str = "\n"
) -> None:
    runs = "{0:<10}".format(f"{runs}")
    iterations = "{0:<14}".format(f"{iterations}")
    mode = "{0:<10}".format(f"{mode}")
    duration = "{0:>13}".format(f"{duration}")
    print(f"{runs} | {iterations} | {mode} | {duration}", end=end)


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
    iterations: int
    conversion_cb: Optional[Callable[[Any], Any]] = None
    preparation_cb: Optional[Callable[[Any], Any]] = None


@dataclass
class BenchmarkParameter:
    data_class: Type[Any]
    object_creation_cb: Callable[[], Any]
    mode_parameter: Dict[Mode, ModeParameter]


benchmark_parameter: Dict[Data, BenchmarkParameter] = {
    Data.benchmark: BenchmarkParameter(
        BenchmarkClass,
        get_random_benchmark_object,
        {
            Mode.creation: ModeParameter(58000),
            Mode.to_bytes: ModeParameter(2200, to_bytes),
            Mode.from_bytes: ModeParameter(3600, BenchmarkClass.from_bytes, to_bytes),
            Mode.to_json: ModeParameter(1100, BenchmarkClass.to_json_dict),
            Mode.from_json: ModeParameter(930, BenchmarkClass.from_json_dict, BenchmarkClass.to_json_dict),
        },
    ),
    Data.full_block: BenchmarkParameter(
        FullBlock,
        rand_full_block,
        {
            Mode.creation: ModeParameter(43000),
            Mode.to_bytes: ModeParameter(9650, to_bytes),
            Mode.from_bytes: ModeParameter(365, FullBlock.from_bytes, to_bytes),
            Mode.to_json: ModeParameter(2400, FullBlock.to_json_dict),
            Mode.from_json: ModeParameter(335, FullBlock.from_json_dict, FullBlock.to_json_dict),
        },
    ),
}


def run_benchmarks(data: Data, mode: Mode, runs: int, multiplier: int) -> None:
    results: Dict[Data, Dict[Mode, List[int]]] = {}
    for current_data, parameter in benchmark_parameter.items():
        results[current_data] = {}
        if data == Data.all or current_data == data:
            print(f"\nRun {mode.name} benchmarks with the class: {parameter.data_class.__name__}")
            print_row("runs", "iterations/run", "mode", "result [ms]")
            for current_mode, mode_parameter in parameter.mode_parameter.items():
                results[current_data][current_mode] = []
                if mode == Mode.all or current_mode == mode:
                    duration: float
                    iterations: int = mode_parameter.iterations * multiplier
                    for _ in range(max(1, runs)):
                        if current_mode == Mode.creation:
                            duration = benchmark_object_creation(iterations, parameter.object_creation_cb)
                        else:
                            assert mode_parameter.conversion_cb is not None
                            duration = benchmark_conversion(
                                iterations,
                                parameter.object_creation_cb,
                                mode_parameter.conversion_cb,
                                mode_parameter.preparation_cb,
                            )
                        current_duration: int = int(duration * 1000)
                        results[current_data][current_mode].append(current_duration)
                        print_row("last", iterations, current_mode.name, current_duration, "\r")
                    average_duration: int = int(sum(results[current_data][current_mode]) / runs)
                    print_row(runs, iterations, current_mode.name, average_duration)


data_option_help: str = "|".join([d.name for d in Data])
mode_option_help: str = "|".join([m.name for m in Mode])


@click.command()
@click.option("-d", "--data", default=Data.all.name, help=data_option_help)
@click.option("-m", "--mode", default=Mode.all.name, help=mode_option_help)
@click.option("-r", "--runs", default=5, help="Number of benchmark runs to average results")
@click.option("-n", "--multiplier", default=1, help="Multiplier for iterations/run")
def run(data: str, mode: str, runs: int, multiplier: int) -> None:
    try:
        Data[data]
    except Exception:
        raise click.BadOptionUsage("data", f"{data} is not a valid data option. Select one from: " + data_option_help)
    try:
        Mode[mode]
    except Exception:
        raise click.BadOptionUsage("mode", f"{mode} is not a valid mode option. Select one from: " + mode_option_help)
    run_benchmarks(Data[data], Mode[mode], runs, multiplier)


if __name__ == "__main__":
    run()  # pylint: disable = no-value-for-parameter
