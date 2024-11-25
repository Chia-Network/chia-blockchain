# Package: utils

from __future__ import annotations

import logging
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Union


@contextmanager
def log_exceptions(
    log: logging.Logger,
    *,
    consume: bool = False,
    message: str = "Caught exception",
    level: int = logging.ERROR,
    show_traceback: bool = True,
    exceptions_to_process: Union[type[BaseException], tuple[type[BaseException], ...]] = Exception,
) -> Iterator[None]:
    try:
        yield
    except exceptions_to_process as e:
        message = f"{message}: {type(e).__name__}: {e}"
        if show_traceback:
            message += f"\n{traceback.format_exc()}"

        log.log(level, message)

        if not consume:
            raise
