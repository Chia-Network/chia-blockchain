from __future__ import annotations

import logging
import time
from re import split
from time import sleep

import pytest

from chia.util.logging import TimedDuplicateFilter


def test_logging_filter(caplog: pytest.LogCaptureFixture) -> None:
    log_interval_secs = 1
    num_logs = 11
    sleep_secs = 0.095

    log = logging.getLogger()
    log.addFilter(TimedDuplicateFilter("Filter this log message.*", log_interval_secs))
    last_time = time.monotonic()

    for n in range(num_logs):
        with caplog.at_level(logging.WARNING):
            log.warning(f"Filter this log message {n}")
            now = time.monotonic()
            print(now - last_time)
            sleep(min(0.0, now - last_time))
            last_time = now

    assert len(split("\n", caplog.text)) <= ((num_logs * sleep_secs) / log_interval_secs) + 1


def test_dont_filter_non_matches(caplog: pytest.LogCaptureFixture) -> None:
    log = logging.getLogger()
    log.addFilter(TimedDuplicateFilter("Filter this log message.*", 10))

    num_log_statements = 13

    for n in range(num_log_statements - 1):
        with caplog.at_level(logging.WARNING):
            log.warning(f"Don't Filter this log message {n}")

    assert len(split("\n", caplog.text)) == num_log_statements
