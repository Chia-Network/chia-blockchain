import os
from pathlib import Path

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHINILLA_ROOT", "~/.chinilla/mainnet"))).resolve()

DEFAULT_KEYS_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHINILLA_KEYS_ROOT", "~/.chinilla_keys"))).resolve()
