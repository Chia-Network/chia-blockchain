import os
from pathlib import Path

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("CANO_ROOT", "~/.cano/mainnet"))).resolve()

DEFAULT_KEYS_ROOT_PATH = Path(os.path.expanduser(os.getenv("CANO_KEYS_ROOT", "~/.cano_keys"))).resolve()
