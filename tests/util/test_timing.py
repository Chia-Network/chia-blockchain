from __future__ import annotations

from typing import Iterator

from chia.util.timing import backoff_times


def test_backoff_yields_initial_first() -> None:
    backoff = backoff_times(initial=3, final=10)
    assert next(backoff) == 3


def test_backoff_yields_final_at_end() -> None:
    def clock(times: Iterator[int] = iter([0, 1])) -> float:
        return next(times)

    backoff = backoff_times(initial=2, final=7, time_to_final=1, clock=clock)
    next(backoff)
    assert next(backoff) == 7


def test_backoff_yields_half_at_halfway() -> None:
    def clock(times: Iterator[int] = iter([0, 1])) -> float:
        return next(times)

    backoff = backoff_times(initial=4, final=6, time_to_final=2, clock=clock)
    next(backoff)
    assert next(backoff) == 5


def test_backoff_saturates_at_final() -> None:
    def clock(times: Iterator[int] = iter([0, 2])) -> float:
        return next(times)

    backoff = backoff_times(initial=1, final=3, time_to_final=1, clock=clock)
    next(backoff)
    assert next(backoff) == 3
