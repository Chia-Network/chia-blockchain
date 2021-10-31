import os
from pathlib import Path

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("shitcoin_ROOT", "~/.shitcoin/mainnet"))).resolve()

DEFAULT_KEYS_ROOT_PATH = Path(os.path.expanduser(os.getenv("shitcoin_KEYS_ROOT", "~/.shitcoin_keys"))).resolve()
