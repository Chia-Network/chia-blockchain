import os
from pathlib import Path

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("SECTOR_ROOT", "~/.sector/mainnet"))).resolve()
