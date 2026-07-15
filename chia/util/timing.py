# Package: utils

from __future__ import annotations

import os
import platform
import sys
import time
from collections.abc import Callable, Iterator
from typing import overload

system_delays = {
    # based on data from https://github.com/Chia-Network/chia-blockchain/pull/13724
    "github": {
        "darwin": 20,
        "linux": 1,
        "win32": 10,
    },
    # arbitrarily selected
    "local": {
        "darwin": 2,
        "linux": 1,
        "win32": 1,
    },
}


def _github_darwin_system_delay() -> int:
    machine = platform.machine().lower()
    runner_arch = os.environ.get("RUNNER_ARCH", "").lower()
    arch = machine or runner_arch
    if arch in {"x86_64", "amd64", "x64"}:
        # Intel macOS runners are slower; tune as the hosted runner tier changes.
        return 40

    return system_delays["github"]["darwin"]


if os.environ.get("GITHUB_ACTIONS") == "true":
    # https://docs.github.com/en/actions/learn-github-actions/environment-variables#default-environment-variables
    if sys.platform == "darwin":
        _system_delay = _github_darwin_system_delay()
    else:
        _system_delay = system_delays["github"][sys.platform]
else:
    try:
        _system_delay = system_delays["local"][sys.platform]
    except KeyError:
        _system_delay = system_delays["local"]["linux"]


@overload
def adjusted_timeout(timeout: float) -> float: ...


@overload
def adjusted_timeout(timeout: None) -> None: ...


def adjusted_timeout(timeout: float | None) -> float | None:
    if timeout is None:
        return None

    return timeout + _system_delay


def backoff_times(
    initial: float = 0.001,
    final: float = 0.100,
    time_to_final: float = 0.5,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[float]:
    # initially implemented as a simple linear backoff

    start = clock()
    delta: float = 0

    result_range = final - initial

    while True:
        yield min(final, initial + ((delta / time_to_final) * result_range))
        delta = clock() - start
