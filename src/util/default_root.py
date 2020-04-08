import os
from pathlib import Path

from src import __version__

DEFAULT_ROOT_PATH = Path(
    os.path.expanduser(
        os.getenv("CHIA_ROOT", "~/.chia/beta-{version}").format(version=__version__)
    )
).resolve()
