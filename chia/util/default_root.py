import os
from pathlib import Path

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/mainnet"))).resolve()
STANDALONE_ROOT_PATH = Path(
    os.path.expanduser(os.getenv("CHIA_STANDALONE_WALLET_ROOT", "~/.chia/standalone_wallet"))
).resolve()

DEFAULT_KEYS_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHIA_KEYS_ROOT", "~/.chia_keys"))).resolve()
