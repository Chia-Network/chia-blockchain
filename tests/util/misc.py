from __future__ import annotations

import contextlib
import dataclasses
import enum
import gc
import math
from concurrent.futures import Future
from inspect import getframeinfo, stack
from statistics import mean
from textwrap import dedent
from time import thread_time
from types import TracebackType
from typing import Callable, Iterator, List, Optional, Type, TypeVar

from typing_extensions import Protocol, final

T = TypeVar("T")


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


def caller_file_and_line(distance: int = 2) -> str:
    caller = getframeinfo(stack()[distance][0])
    return f"{caller.filename}:{caller.lineno}"


@dataclasses.dataclass(frozen=True)
class RuntimeResults:
    start: float
    end: float
    duration: float
    entry_line: str

    def block(self, message: str = "") -> str:
        # The entry line is reported starting at the beginning of the line to trigger
        # PyCharm to highlight as a link to the source.

        return dedent(
            f"""\
            Measuring runtime: {message}
            {self.entry_line}
                run time: {self.duration}
            """
        )


@final
@dataclasses.dataclass(frozen=True)
class AssertRuntimeResults:
    start: float
    end: float
    duration: float
    limit: float
    ratio: float
    entry_line: str
    overhead: float

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

    def block(self, message: str = "") -> str:
        # The entry line is reported starting at the beginning of the line to trigger
        # PyCharm to highlight as a link to the source.

        return dedent(
            f"""\
            Asserting maximum duration: {message}
            {self.entry_line}
                run time: {self.duration}
                 allowed: {self.limit}
                 percent: {self.percent_str()}
                 overhead: {self.overhead}
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


class DurationResultsProtocol(Protocol):
    duration: float


def measure_overhead(
    manager_maker: Callable[[], contextlib.AbstractContextManager[Future[DurationResultsProtocol]]],
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
    message: str = "",
    clock: Callable[[], float] = thread_time,
    gc_mode: GcMode = GcMode.disable,
    calibrate: bool = True,
    print_results: bool = True,
) -> Iterator[Future[RuntimeResults]]:
    entry_line = caller_file_and_line()

    def manager_maker() -> contextlib.AbstractContextManager[Future[RuntimeResults]]:
        return measure_runtime(clock=clock, gc_mode=gc_mode, calibrate=False, print_results=False)

    if calibrate:
        overhead = measure_overhead(manager_maker=manager_maker)  # type: ignore[arg-type]
    else:
        overhead = 0

    results_future = Future[RuntimeResults]()

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
            )
            results_future.set_result(results)

            if print_results:
                print(results.block(message=message))


@final
@dataclasses.dataclass
class AssertMaximumDuration:
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
    message: str
    clock: Callable[[], float]
    gc_mode: GcMode
    calibrate: bool
    print: bool = True
    overhead: float = 0
    entry_line: Optional[str] = None
    _results: Optional[AssertRuntimeResults] = None
    runtime_manager: Optional[contextlib.AbstractContextManager[Future[RuntimeResults]]] = None
    runtime_results_callable: Optional[Future[RuntimeResults]] = None

    def results(self) -> AssertRuntimeResults:
        if self._results is None:
            raise Exception("runtime results not yet available")

        return self._results

    def __enter__(self) -> Future[AssertRuntimeResults]:
        self.entry_line = caller_file_and_line()
        if self.calibrate:

            def manager_maker() -> contextlib.AbstractContextManager[Future[AssertRuntimeResults]]:
                return dataclasses.replace(self, seconds=math.inf, calibrate=False, print=False)

            self.overhead = measure_overhead(manager_maker=manager_maker)  # type: ignore[arg-type]

        self.runtime_manager = measure_runtime(
            clock=self.clock, gc_mode=self.gc_mode, calibrate=False, print_results=False
        )
        self.runtime_results_callable = self.runtime_manager.__enter__()
        self.results_callable = Future[AssertRuntimeResults]()

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
            print(results.block(message=self.message))

        if exc_type is None:
            __tracebackhide__ = True
            assert runtime.duration < self.seconds, results.message()


def assert_maximum_duration(
    seconds: float,
    message: str = "",
    clock: Callable[[], float] = thread_time,
    gc_mode: GcMode = GcMode.disable,
    calibrate: bool = True,
) -> AssertMaximumDuration:
    return AssertMaximumDuration(seconds=seconds, message=message, clock=clock, gc_mode=gc_mode, calibrate=calibrate)
