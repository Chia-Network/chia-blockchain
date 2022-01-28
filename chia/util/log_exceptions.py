from contextlib import contextmanager
import logging
import traceback
from typing import Iterator


@contextmanager
def log_exceptions(log: logging.Logger) -> Iterator[None]:
    try:
        yield
    except Exception as e:
        log.error(f"Caught Exception: {e}. Traceback: {traceback.format_exc()}")
