# Package: utils

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/mainnet"))).resolve()

DEFAULT_KEYS_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHIA_KEYS_ROOT", "~/.chia_keys"))).resolve()

SIMULATOR_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHIA_SIMULATOR_ROOT", "~/.chia/simulator"))).resolve()


def resolve_root_path(*, override: Optional[Path]) -> Path:
    candidates = [
        override,
        os.environ.get("CHIA_ROOT"),
        "~/.chia/mainnet",
    ]

    for candidate in candidates:
        if candidate is not None:
            return Path(candidate).expanduser().resolve()

    raise RuntimeError("unreachable: last candidate is hardcoded to be found")
