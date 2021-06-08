import os
from pathlib import Path

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/testnet8"))).resolve()
