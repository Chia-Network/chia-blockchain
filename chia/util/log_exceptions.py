from __future__ import annotations

import logging
import traceback
from contextlib import contextmanager
from typing import Union


@contextmanager
def log_exceptions(
    log: logging.Logger,
    *, 
    consume: bool = False,
    level: int = logging.ERROR,
    show_traceback: bool = True,
    exceptions_to_catch: Union[Type[BaseException], Tuple[Type[BaseException], ...]] = Exception,
 ):
    try:
        yield
    except exceptions_to_catch as e:
        message = f"Caught exception: {type(e).__name__}: {e}"
        if show_traceback:
            message += f"\n{traceback.format_exc()}"

        log.log(level, message)

        if not consume:
            raise
