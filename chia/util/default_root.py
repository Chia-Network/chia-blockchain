import os
from pathlib import Path

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.sit/mainnet"))).resolve()

DEFAULT_KEYS_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHIA_KEYS_ROOT", "~/.sit_keys"))).resolve()
