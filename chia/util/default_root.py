from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/mainnet"))).resolve()

DEFAULT_KEYS_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHIA_KEYS_ROOT", "~/.chia_keys"))).resolve()

SIMULATOR_ROOT_PATH = Path(
    os.path.expanduser(os.getenv("CHIA_SIMULATOR_ROOT", f"{DEFAULT_ROOT_PATH.parent}/simulator"))
).resolve()
