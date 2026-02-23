from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path

from chia.util.chia_logging import initialize_logging


def test_initialize_logging_timestamp_includes_timezone_offset(tmp_path: Path) -> None:
    # Regression coverage for issue #8802.
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    for handler in original_handlers:
        root_logger.removeHandler(handler)

    try:
        initialize_logging(
            service_name="test-service",
            logging_config={
                "log_stdout": False,
                "log_filename": "log/debug.log",
                "log_level": "WARNING",
            },
            root_path=tmp_path,
        )

        [handler] = root_logger.handlers
        record = logging.LogRecord(
            name="chia.test",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="timezone test",
            args=(),
            exc_info=None,
        )
        timestamp = handler.format(record).split(" ", maxsplit=1)[0]
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{4})\.\d{3}$", timestamp) is not None
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            with contextlib.suppress(Exception):
                handler.close()
        for handler in original_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(original_level)
