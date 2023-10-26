from __future__ import annotations

import contextlib
import dataclasses
import enum
import functools
import gc
import logging
import os
import pathlib
import subprocess
import sys
from concurrent.futures import Future
from inspect import getframeinfo, stack
from statistics import mean
from textwrap import dedent
from time import thread_time
from types import TracebackType
from typing import Any, Callable, Collection, Iterator, List, Optional, TextIO, Tuple, Type, Union

import pytest
from chia_rs import Coin
from typing_extensions import Protocol, final

import chia
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.wallet.util.compute_hints import HintedCoin
from tests.core.data_layer.util import ChiaRoot


class GcMode(enum.Enum):
    nothing = enum.auto
    precollect = enum.auto
    disable = enum.auto
    enable = enum.auto


@contextlib.contextmanager
def manage_gc(mode: GcMode) -> Iterator[None]:
    if mode == GcMode.nothing:
        yield
    elif mode == GcMode.precollect:
        gc.collect()
        yield
    elif mode == GcMode.disable:
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            yield
        finally:
            if was_enabled:
                gc.enable()
    elif mode == GcMode.enable:
        was_enabled = gc.isenabled()
        gc.enable()
        try:
            yield
        finally:
            if not was_enabled:
                gc.disable()


def caller_file_and_line(distance: int = 1) -> Tuple[str, int]:
    caller = getframeinfo(stack()[distance + 1][0])
    return caller.filename, caller.lineno


@dataclasses.dataclass(frozen=True)
class RuntimeResults:
    start: float
    end: float
    duration: float
    entry_file: str
    entry_line: int
    overhead: Optional[float]

    def block(self, label: str = "") -> str:
        # The entry line is reported starting at the beginning of the line to trigger
        # PyCharm to highlight as a link to the source.

        return dedent(
            f"""\
            Measuring runtime: {label}
            {self.entry_line}
                run time: {self.duration}
                overhead: {self.overhead if self.overhead is not None else "not measured"}
            """
        )


@final
@dataclasses.dataclass(frozen=True)
class AssertRuntimeResults:
    start: float
    end: float
    duration: float
    entry_file: str
    entry_line: int
    overhead: Optional[float]
    limit: float
    ratio: float

    @classmethod
    def from_runtime_results(
        cls, results: RuntimeResults, limit: float, entry_file: str, entry_line: int, overhead: Optional[float]
    ) -> AssertRuntimeResults:
        return cls(
            start=results.start,
            end=results.end,
            duration=results.duration,
            limit=limit,
            ratio=results.duration / limit,
            entry_file=entry_file,
            entry_line=entry_line,
            overhead=overhead,
        )

    def block(self, label: str = "") -> str:
        # The entry line is reported starting at the beginning of the line to trigger
        # PyCharm to highlight as a link to the source.

        return dedent(
            f"""\
            Asserting maximum duration: {label}
            {self.entry_file}:{self.entry_line}
                run time: {self.duration}
                overhead: {self.overhead if self.overhead is not None else "not measured"}
                 allowed: {self.limit}
                 percent: {self.percent_str()}
            """
        )

    def message(self) -> str:
        return f"{self.duration} seconds not less than {self.limit} seconds ( {self.percent_str()} )"

    def passed(self) -> bool:
        return self.duration < self.limit

    def percent(self) -> float:
        return self.ratio * 100

    def percent_str(self) -> str:
        return f"{self.percent():.0f} %"


def measure_overhead(
    manager_maker: Callable[
        [], contextlib.AbstractContextManager[Union[Future[RuntimeResults], Future[AssertRuntimeResults]]]
    ],
    cycles: int = 10,
) -> float:
    times: List[float] = []

    for _ in range(cycles):
        with manager_maker() as results:
            pass

        times.append(results.result(timeout=0).duration)

    overhead = mean(times)

    return overhead


@contextlib.contextmanager
def measure_runtime(
    label: str = "",
    clock: Callable[[], float] = thread_time,
    gc_mode: GcMode = GcMode.disable,
    overhead: Optional[float] = None,
    print_results: bool = True,
) -> Iterator[Future[RuntimeResults]]:
    entry_file, entry_line = caller_file_and_line()

    results_future: Future[RuntimeResults] = Future()

    with manage_gc(mode=gc_mode):
        start = clock()

        try:
            yield results_future
        finally:
            end = clock()

            duration = end - start
            if overhead is not None:
                duration -= overhead

            results = RuntimeResults(
                start=start,
                end=end,
                duration=duration,
                entry_file=entry_file,
                entry_line=entry_line,
                overhead=overhead,
            )
            results_future.set_result(results)

            if print_results:
                print(results.block(label=label))


@final
@dataclasses.dataclass
class _AssertRuntime:
    """Prepare for, measure, and assert about the time taken by code in the context.

    Defaults are set for single-threaded CPU usage timing without garbage collection.

    In general, there is no generally correct setup for benchmarking.  Only measuring
    a single thread's time using the CPU is not very useful for multithreaded or
    multiprocessed code.  Disabling garbage collection, or forcing it ahead of time,
    makes the benchmark not identify any issues the code may introduce in terms of
    actually causing relevant gc slowdowns.  And so on...

    Produces output of the following form.

        Asserting maximum duration: full block
        /home/altendky/repos/chia-blockchain/tests/core/full_node/test_performance.py:187
            run time: 0.027789528900002837
            allowed: 0.1
            percent: 28 %
    """

    # A class is only being used here, to make __tracebackhide__ work.
    # https://github.com/pytest-dev/pytest/issues/2057

    seconds: float
    label: str = ""
    clock: Callable[[], float] = thread_time
    gc_mode: GcMode = GcMode.disable
    print: bool = True
    overhead: Optional[float] = None
    entry_file: Optional[str] = None
    entry_line: Optional[int] = None
    _results: Optional[AssertRuntimeResults] = None
    runtime_manager: Optional[contextlib.AbstractContextManager[Future[RuntimeResults]]] = None
    runtime_results_callable: Optional[Future[RuntimeResults]] = None
    enable_assertion: bool = True
    record_property: Optional[Callable[[str, object], None]] = None

    def __enter__(self) -> Future[AssertRuntimeResults]:
        self.entry_file, self.entry_line = caller_file_and_line()

        self.runtime_manager = measure_runtime(
            clock=self.clock, gc_mode=self.gc_mode, overhead=self.overhead, print_results=False
        )
        self.runtime_results_callable = self.runtime_manager.__enter__()
        self.results_callable: Future[AssertRuntimeResults] = Future()

        return self.results_callable

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if (
            self.entry_file is None
            or self.entry_line is None
            or self.runtime_manager is None
            or self.runtime_results_callable is None
        ):
            raise Exception("Context manager must be entered before exiting")

        self.runtime_manager.__exit__(exc_type, exc, traceback)

        runtime = self.runtime_results_callable.result(timeout=0)
        results = AssertRuntimeResults.from_runtime_results(
            results=runtime,
            limit=self.seconds,
            entry_file=self.entry_file,
            entry_line=self.entry_line,
            overhead=self.overhead,
        )

        self.results_callable.set_result(results)

        if self.print:
            print(results.block(label=self.label))

        if self.record_property is not None:
            self.record_property(f"duration:{self.label}", results.duration)

            relative_path_str = (
                pathlib.Path(results.entry_file).relative_to(pathlib.Path(chia.__file__).parent.parent).as_posix()
            )

            self.record_property(f"path:{self.label}", relative_path_str)
            self.record_property(f"line:{self.label}", results.entry_line)
            self.record_property(f"limit:{self.label}", self.seconds)

        if exc_type is None and self.enable_assertion:
            __tracebackhide__ = True
            assert runtime.duration < self.seconds, results.message()


@final
@dataclasses.dataclass
class BenchmarkRunner:
    enable_assertion: bool = True
    label: Optional[str] = None
    overhead: Optional[float] = None
    record_property: Optional[Callable[[str, object], None]] = None

    @functools.wraps(_AssertRuntime)
    def assert_runtime(self, *args: Any, **kwargs: Any) -> _AssertRuntime:
        kwargs.setdefault("enable_assertion", self.enable_assertion)
        kwargs.setdefault("overhead", self.overhead)
        kwargs.setdefault("record_property", self.record_property)
        return _AssertRuntime(*args, **kwargs)


@contextlib.contextmanager
def assert_rpc_error(error: str) -> Iterator[None]:
    with pytest.raises(ValueError) as exception_info:
        yield
    assert error in exception_info.value.args[0]["error"]


@contextlib.contextmanager
def closing_chia_root_popen(chia_root: ChiaRoot, args: List[str]) -> Iterator[subprocess.Popen[Any]]:
    environment = {**os.environ, "CHIA_ROOT": os.fspath(chia_root.path)}

    with subprocess.Popen(args=args, env=environment) as process:
        try:
            yield process
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


# https://github.com/pytest-dev/pytest/blob/7.3.1/src/_pytest/mark/__init__.py#L45
Marks = Union[pytest.MarkDecorator, Collection[Union[pytest.MarkDecorator, pytest.Mark]]]


class DataCase(Protocol):
    marks: Marks

    @property
    def id(self) -> str:
        ...


def datacases(*cases: DataCase, _name: str = "case") -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        argnames=_name,
        argvalues=[pytest.param(case, id=case.id, marks=case.marks) for case in cases],
    )


class DataCasesDecorator(Protocol):
    def __call__(self, *cases: DataCase, _name: str = "case") -> pytest.MarkDecorator:
        ...


def named_datacases(name: str) -> DataCasesDecorator:
    return functools.partial(datacases, _name=name)


@dataclasses.dataclass
class CoinGenerator:
    _seed: int = -1

    def _get_hash(self) -> bytes32:
        self._seed += 1
        return std_hash(self._seed.to_bytes(length=32, byteorder="big"))

    def _get_amount(self) -> uint64:
        self._seed += 1
        return uint64(self._seed)

    def get(self, parent_coin_id: Optional[bytes32] = None, include_hint: bool = True) -> HintedCoin:
        if parent_coin_id is None:
            parent_coin_id = self._get_hash()
        hint = None
        if include_hint:
            hint = self._get_hash()
        return HintedCoin(Coin(parent_coin_id, self._get_hash(), self._get_amount()), hint)


def coin_creation_args(hinted_coin: HintedCoin) -> List[Any]:
    if hinted_coin.hint is not None:
        memos = [hinted_coin.hint]
    else:
        memos = []
    return [ConditionOpcode.CREATE_COIN, hinted_coin.coin.puzzle_hash, hinted_coin.coin.amount, memos]


def create_logger(file: TextIO = sys.stdout) -> logging.Logger:
    logger = logging.getLogger()
    logger.setLevel(level=logging.DEBUG)
    stream_handler = logging.StreamHandler(stream=file)
    log_date_format = "%Y-%m-%dT%H:%M:%S"
    file_log_formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
        datefmt=log_date_format,
    )
    stream_handler.setFormatter(file_log_formatter)
    logger.addHandler(hdlr=stream_handler)

    return logger
