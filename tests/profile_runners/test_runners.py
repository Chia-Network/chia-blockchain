from __future__ import annotations

import sys
import time


limits = {
    "darwin": 5,
    "linux": 0.5,
    "win32": 0.5,
}


limit = limits[sys.platform]


def test_profile_pauses() -> None:
    nominal_sleep = 0.1
    duration = 20 * 60
    periods = []

    start = time.monotonic()
    end = start + duration

    last = start

    while True:
        time.sleep(nominal_sleep)
        now = time.monotonic()

        period = now - last
        periods.append(period)
        print(period)

        if now > end:
            break

        last = now

    assert [period for period in periods if period >= limit] == [], f"periods found longer than {limit} seconds"
