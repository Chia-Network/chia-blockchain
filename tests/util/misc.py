import contextlib
import gc
from time import perf_counter
from typing import Callable, Iterator


@contextlib.contextmanager
def assert_maximum_duration(seconds: float, clock: Callable[[], float] = perf_counter) -> Iterator[None]:
    __tracebackhide__ = True

    gc.collect()
    start = clock()
    yield
    end = clock()
    duration = end - start
    print(f"run time: {duration}")
    assert duration < seconds
