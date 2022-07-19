import os
from pathlib import Path
from typing import Union


def path_from_root(root: Path, path_str: Union[str, Path]) -> Path:
    """
    If path is relative, prepend root
    If path is absolute, return it directly.
    """
    root = Path(os.path.expanduser(str(root)))
    path = Path(path_str)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def mkdir(path_str: Union[str, Path]) -> None:
    """
    Create the existing directory (and its parents) if necessary.
    """
    path = Path(path_str)
    path.mkdir(parents=True, exist_ok=True)


def make_path_relative(path_str: Union[str, Path], root: Path) -> Path:
    """
    Try to make the given path relative, given the default root.
    """
    path = Path(path_str)
    try:
        path = path.relative_to(root)
    except ValueError:
        pass
    return path
