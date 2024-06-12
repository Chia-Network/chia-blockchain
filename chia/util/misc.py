from __future__ import annotations

import os
import sys
from inspect import getframeinfo, stack
from pathlib import Path
from typing import Iterable, List, Tuple, Type, TypeVar, get_args, get_origin

import psutil

T = TypeVar("T")


def available_logical_cores() -> int:
    if sys.platform == "darwin":
        count = os.cpu_count()
        assert count is not None
        return count

    cores = len(psutil.Process().cpu_affinity())

    if sys.platform == "win32":
        cores = min(61, cores)  # https://github.com/python/cpython/issues/89240

    return cores


def caller_file_and_line(distance: int = 1, relative_to: Iterable[Path] = ()) -> Tuple[str, int]:
    caller = getframeinfo(stack()[distance + 1][0])

    caller_path = Path(caller.filename)
    options: List[str] = [caller_path.as_posix()]
    for path in relative_to:
        try:
            options.append(caller_path.relative_to(path).as_posix())
        except ValueError:
            pass

    return min(options, key=len), caller.lineno


def satisfies_hint(obj: T, type_hint: Type[T]) -> bool:
    """
    Check if an object satisfies a type hint.
    This is a simplified version of `isinstance` that also handles generic types.
    """
    # Start from the initial type hint
    object_hint_pairs = [(obj, type_hint)]
    while len(object_hint_pairs) > 0:
        obj, type_hint = object_hint_pairs.pop()
        origin = get_origin(type_hint)
        args = get_args(type_hint)
        if origin:
            # Handle generic types
            if not isinstance(obj, origin):
                return False
            if len(args) > 0:
                # Tuple[T, ...] gets handled just like List[T]
                if origin is list or (origin is tuple and args[-1] is Ellipsis):
                    object_hint_pairs.extend((item, args[0]) for item in obj)
                elif origin is tuple:
                    object_hint_pairs.extend((item, arg) for item, arg in zip(obj, args))
                elif origin is dict:
                    object_hint_pairs.extend((k, args[0]) for k in obj.keys())
                    object_hint_pairs.extend((v, args[1]) for v in obj.values())
                else:
                    raise NotImplementedError(f"Type {origin} is not yet supported")
        else:
            # Handle concrete types
            if type(obj) is not type_hint:
                return False
    return True
