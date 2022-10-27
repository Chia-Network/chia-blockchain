from __future__ import annotations

import time


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

    assert max(periods) < 5
