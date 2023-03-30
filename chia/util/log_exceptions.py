from __future__ import annotations

import logging
import traceback
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def log_exceptions(log: logging.Logger, *, consume: bool = False) -> Iterator[None]:
    try:
        yield
    except Exception as e:
        log.error(f"Caught Exception: {e}. Traceback: {traceback.format_exc()}")
        if not consume:
            raise
