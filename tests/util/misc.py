import gc
from dataclasses import dataclass
from inspect import getframeinfo, stack
from textwrap import dedent
from time import thread_time
from types import TracebackType
from typing import Callable, Optional, Type


def caller_file_and_line(distance: int = 2) -> str:
    caller = getframeinfo(stack()[distance][0])
    return f"{caller.filename}:{caller.lineno}"


@dataclass(frozen=True)
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


@dataclass
class AssertMaximumDuration:
    seconds: float
    clock: Callable[[], float]
    start: Optional[float] = None
    entry_line: Optional[str] = None
    results: Optional[AssertMaximumDurationResults] = None

    def __enter__(self) -> None:
        self.entry_line = caller_file_and_line()
        gc.collect()
        self.start = self.clock()

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        end = self.clock()

        if self.start is None or self.entry_line is None:
            raise Exception("Context manager must be entered before exiting")

        duration = end - self.start
        ratio = duration / self.seconds

        self.results = AssertMaximumDurationResults(
            start=self.start,
            end=end,
            duration=duration,
            limit=self.seconds,
            ratio=ratio,
            entry_line=self.entry_line,
        )

        print(self.results.block())

        if exc_type is None:
            __tracebackhide__ = True
            assert self.results.passed(), self.results.message()


def assert_maximum_duration(seconds: float, clock: Callable[[], float] = thread_time) -> AssertMaximumDuration:
    return AssertMaximumDuration(seconds=seconds, clock=clock)
