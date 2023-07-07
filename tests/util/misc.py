from __future__ import annotations

import contextlib
import dataclasses
import enum
import functools
import gc
import math
import os
import subprocess
from concurrent.futures import Future
from inspect import getframeinfo, stack
from statistics import mean
from textwrap import dedent
from time import thread_time
from types import TracebackType
from typing import Any, Callable, Collection, Iterator, List, Optional, Type, Union

import pytest
from chia_rs import Coin
from typing_extensions import Protocol, final

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
    if mode == GcMode.precollect:
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


def caller_file_and_line(distance: int = 1) -> str:
    caller = getframeinfo(stack()[distance + 1][0])
    return f"{caller.filename}:{caller.lineno}"


@dataclasses.dataclass(frozen=True)
class RuntimeResults:
    start: float
    end: float
    duration: float
    entry_line: str
    overhead: float

    def block(self, label: str = "") -> str:
        # The entry line is reported starting at the beginning of the line to trigger
        # PyCharm to highlight as a link to the source.

        return dedent(
            f"""\
            Measuring runtime: {label}
            {self.entry_line}
                run time: {self.duration}
                overhead: {self.overhead}
            """
        )


@final
@dataclasses.dataclass(frozen=True)
class AssertRuntimeResults:
    start: float
    end: float
    duration: float
    entry_line: str
    overhead: float
    limit: float
    ratio: float

    @classmethod
    def from_runtime_results(
        cls, results: RuntimeResults, limit: float, entry_line: str, overhead: float
    ) -> AssertRuntimeResults:
        return cls(
            start=results.start,
            end=results.end,
            duration=results.duration,
            limit=limit,
            ratio=results.duration / limit,
            entry_line=entry_line,
            overhead=overhead,
        )

    def block(self, label: str = "") -> str:
        # The entry line is reported starting at the beginning of the line to trigger
        # PyCharm to highlight as a link to the source.

        return dedent(
            f"""\
            Asserting maximum duration: {label}
            {self.entry_line}
                run time: {self.duration}
                overhead: {self.overhead}
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
    calibrate: bool = True,
    print_results: bool = True,
) -> Iterator[Future[RuntimeResults]]:
    entry_line = caller_file_and_line()

    def manager_maker() -> contextlib.AbstractContextManager[Future[RuntimeResults]]:
        return measure_runtime(clock=clock, gc_mode=gc_mode, calibrate=False, print_results=False)

    if calibrate:
        overhead = measure_overhead(manager_maker=manager_maker)
    else:
        overhead = 0

    results_future: Future[RuntimeResults] = Future()

    with manage_gc(mode=gc_mode):
        start = clock()

        try:
            yield results_future
        finally:
            end = clock()

            duration = end - start
            duration -= overhead

            results = RuntimeResults(
                start=start,
                end=end,
                duration=duration,
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
    calibrate: bool = True
    print: bool = True
    overhead: float = 0
    entry_line: Optional[str] = None
    _results: Optional[AssertRuntimeResults] = None
    runtime_manager: Optional[contextlib.AbstractContextManager[Future[RuntimeResults]]] = None
    runtime_results_callable: Optional[Future[RuntimeResults]] = None

    def __enter__(self) -> Future[AssertRuntimeResults]:
        self.entry_line = caller_file_and_line()
        if self.calibrate:

            def manager_maker() -> contextlib.AbstractContextManager[Future[AssertRuntimeResults]]:
                return dataclasses.replace(self, seconds=math.inf, calibrate=False, print=False)

            self.overhead = measure_overhead(manager_maker=manager_maker)

        self.runtime_manager = measure_runtime(
            clock=self.clock, gc_mode=self.gc_mode, calibrate=False, print_results=False
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
        if self.entry_line is None or self.runtime_manager is None or self.runtime_results_callable is None:
            raise Exception("Context manager must be entered before exiting")

        self.runtime_manager.__exit__(exc_type, exc, traceback)

        runtime = self.runtime_results_callable.result(timeout=0)
        results = AssertRuntimeResults.from_runtime_results(
            results=runtime,
            limit=self.seconds,
            entry_line=self.entry_line,
            overhead=self.overhead,
        )

        self.results_callable.set_result(results)

        if self.print:
            print(results.block(label=self.label))

        if exc_type is None:
            __tracebackhide__ = True
            assert runtime.duration < self.seconds, results.message()


# Related to the comment above about needing a class vs. using the context manager
# decorator, this is just here to retain the function-style naming as the public
# interface.  Hopefully we can switch away from the class at some point.
assert_runtime = _AssertRuntime


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
        return std_hash(self._seed)

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
