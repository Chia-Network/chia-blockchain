from __future__ import annotations

import logging
import re
import time
from typing import Pattern


class TimedDuplicateFilter(logging.Filter):
    last_log_time: float
    regex: Pattern[str]
    min_time_wait_secs: int

    def __init__(self, regex_str: str, min_time_wait_secs: int, name: str = ""):
        super(TimedDuplicateFilter, self).__init__(name)
        self.last_log_time = time.monotonic()
        self.regex = re.compile(regex_str)
        self.min_time_wait_secs = min_time_wait_secs

    def filter(self, record: logging.LogRecord) -> bool:
        _ = super(TimedDuplicateFilter, self).filter(record)
        if not _:
            return False

        msg = record.getMessage()

        if self.regex.match(msg):
            now = time.monotonic()
            if now - self.last_log_time > self.min_time_wait_secs:
                self.last_log_time = now
                return True
            return False
        else:
            return True
