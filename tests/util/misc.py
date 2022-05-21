import contextlib
import dataclasses
import enum
import gc
import math
from inspect import getframeinfo, stack
from statistics import mean
from textwrap import dedent
from time import thread_time
from types import TracebackType
from typing import Callable, Iterator, List, Optional, Type


class GcMode(enum.Enum):
    nothing = enum.auto
    precollect = enum.auto
    disable = enum.auto
    enable = enum.auto


@contextlib.contextmanager
def gc_mode(mode: GcMode) -> Iterator[None]:
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
class AssertMaximumDurationResults:
    start: float
    end: float
    duration: float
    limit: float
    ratio: float
    entry_line: str

    def block(self) -> str:
        # The entry line is reported starting at the beginning of the line to trigger
        # PyCharm to highlight as a link to the source.
        return dedent(
            f"""\
            Asserting maximum duration:
            {self.entry_line}
                run time: {self.duration}
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


@dataclasses.dataclass
class AssertMaximumDuration:
    """Prepare for, measure, and assert about the time taken by code in the context.

    Defaults are set for single-threaded CPU usage timing without garbage collection.

    In general, there is no generally correct setup for benchmarking.  Only measuring
    a single thread's time using the CPU is not very useful for multithreaded or
    multiprocessed code.  Disabling garbage collection, or forcing it ahead of time,
    makes the benchmark not identify any issues the code may introduce in terms of
    actually causing relevant gc slowdowns.  And so on...
    """

    seconds: float
    clock: Callable[[], float]
    gc_mode: GcMode
    calibrate: bool
    print: bool = True
    compensation: float = 0
    start: Optional[float] = None
    entry_line: Optional[str] = None
    results: Optional[AssertMaximumDurationResults] = None
    gc_manager: Optional[contextlib.AbstractContextManager[None]] = None

    def calibrate_compensation(self) -> float:
        times: List[float] = []
        for _ in range(10):
            manager = dataclasses.replace(self, seconds=math.inf, calibrate=False, print=False)
            with manager:
                pass
            if manager.results is None:
                raise Exception("manager failed to provide results")
            times.append(manager.results.duration)
        compensation = mean(times)

        return compensation

    def __enter__(self) -> None:
        self.entry_line = caller_file_and_line()
        if self.calibrate:
            self.compensation = self.calibrate_compensation()
        self.gc_manager = gc_mode(mode=self.gc_mode)
        self.gc_manager.__enter__()
        self.start = self.clock()

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        end = self.clock()

        if self.start is None or self.entry_line is None or self.gc_manager is None:
            raise Exception("Context manager must be entered before exiting")

        self.gc_manager.__exit__(exc_type, exc, traceback)

        duration = end - self.start
        duration -= self.compensation
        ratio = duration / self.seconds

        self.results = AssertMaximumDurationResults(
            start=self.start,
            end=end,
            duration=duration,
            limit=self.seconds,
            ratio=ratio,
            entry_line=self.entry_line,
        )

        if self.print:
            print(self.results.block())

        if exc_type is None:
            __tracebackhide__ = True
            assert self.results.passed(), self.results.message()


def assert_maximum_duration(
    seconds: float,
    clock: Callable[[], float] = thread_time,
    gc_mode: GcMode = GcMode.disable,
    calibrate: bool = True,
) -> AssertMaximumDuration:
    return AssertMaximumDuration(seconds=seconds, clock=clock, gc_mode=gc_mode, calibrate=calibrate)
