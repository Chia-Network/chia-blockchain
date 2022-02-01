from contextlib import contextmanager
import logging
import traceback


@contextmanager
def log_exceptions(log: logging.Logger):
    try:
        yield
    except Exception as e:
        log.error(f"Caught Exception: {e}. Traceback: {traceback.format_exc()}")
