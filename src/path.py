import os
from pathlib import Path

from src import __version__

DEFAULT_ROOT_PATH = Path(
    os.path.expanduser(os.getenv("CHIA_ROOT", "~/.chia/beta-%s" % __version__))
).resolve()


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
    """
    Create the existing directory (and its parents) if necessary.
    """
    Path(path_str).mkdir(parents=True, exist_ok=True)


def make_path_relative(path_str: str) -> Path:
    """
    Try to make the given path relative, given the default root.
    """
    path = Path(path_str)
    try:
        path = path.relative_to(DEFAULT_ROOT_PATH)
    except ValueError:
        pass
    return path
