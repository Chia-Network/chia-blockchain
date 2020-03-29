import os
from pathlib import Path

from src import version

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/prerelease-%s" % version)))


def path_from_root(path_str: str = ".", root_path: Path = DEFAULT_ROOT_PATH) -> Path:
    """
    Return a new path from the given one, expanding "~" if present.
    If path is relative, prepend $CHIA_ROOT
    If path is absolute, return it directly.
    This lets us use "~" and other absolute paths in config files.
    """
    path = Path(os.path.expanduser(path_str))
    if not path.is_absolute():
        path = root_path / path
    return path


def mkdir(path_str: str) -> None:
    Path(path_str).mkdir(parents=True, exist_ok=True)
