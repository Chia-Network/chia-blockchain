from __future__ import annotations

from inspect import getframeinfo, stack
from pathlib import Path
from typing import Iterable


def caller_file_and_line(distance: int = 1, relative_to: Iterable[Path] = ()) -> tuple[str, int]:
    caller = getframeinfo(stack()[distance + 1][0])

    caller_path = Path(caller.filename)
    options: list[str] = [caller_path.as_posix()]
    for path in relative_to:
        try:
            options.append(caller_path.relative_to(path).as_posix())
        except ValueError:
            pass

    return min(options, key=len), caller.lineno
