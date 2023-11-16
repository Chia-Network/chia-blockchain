from __future__ import annotations

import os
import sys
from typing import Optional, overload

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


if os.environ.get("GITHUB_ACTIONS") == "true":
    # https://docs.github.com/en/actions/learn-github-actions/environment-variables#default-environment-variables
    _system_delay = system_delays["github"][sys.platform]
else:
    _system_delay = system_delays["local"][sys.platform]


@overload
def adjusted_timeout(timeout: float) -> float:
    ...


@overload
def adjusted_timeout(timeout: None) -> None:
    ...


def adjusted_timeout(timeout: Optional[float]) -> Optional[float]:
    if timeout is None:
        return None

    return timeout + _system_delay
