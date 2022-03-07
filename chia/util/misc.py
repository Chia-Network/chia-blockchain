def format_bytes(bytes: int) -> str:

    if not isinstance(bytes, int) or bytes < 0:
        return "Invalid"

    LABELS = ("MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")
    BASE = 1024
    value = bytes / BASE
    for label in LABELS:
        value /= BASE
        if value < BASE:
            return f"{value:.3f} {label}"

    return f"{value:.3f} {LABELS[-1]}"


def format_minutes(minutes: int) -> str:

    if not isinstance(minutes, int):
        return "Invalid"

    if minutes == 0:
        return "Now"

    hour_minutes = 60
    day_minutes = 24 * hour_minutes
    week_minutes = 7 * day_minutes
    months_minutes = 43800
    year_minutes = 12 * months_minutes

    years = int(minutes / year_minutes)
    months = int(minutes / months_minutes)
    weeks = int(minutes / week_minutes)
    days = int(minutes / day_minutes)
    hours = int(minutes / hour_minutes)

    def format_unit_string(str_unit: str, count: int) -> str:
        return f"{count} {str_unit}{('s' if count > 1 else '')}"

    def format_unit(unit: str, count: int, unit_minutes: int, next_unit: str, next_unit_minutes: int) -> str:
        formatted = format_unit_string(unit, count)
        minutes_left = minutes % unit_minutes
        if minutes_left >= next_unit_minutes:
            formatted += " and " + format_unit_string(next_unit, int(minutes_left / next_unit_minutes))
        return formatted

    if years > 0:
        return format_unit("year", years, year_minutes, "month", months_minutes)
    if months > 0:
        return format_unit("month", months, months_minutes, "week", week_minutes)
    if weeks > 0:
        return format_unit("week", weeks, week_minutes, "day", day_minutes)
    if days > 0:
        return format_unit("day", days, day_minutes, "hour", hour_minutes)
    if hours > 0:
        return format_unit("hour", hours, hour_minutes, "minute", 1)
    if minutes > 0:
        return format_unit_string("minute", minutes)

    return "Unknown"


def prompt_yes_no(prompt: str = "(y/n) ") -> bool:
    while True:
        response = str(input(prompt)).lower().strip()
        ch = response[:1]
        if ch == "y":
            return True
        elif ch == "n":
            return False


import asyncio
import dataclasses
import logging
import traceback


@dataclasses.dataclass
class LoggingLock:
    logger: logging.Logger
    id: str
    lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)

    async def __aenter__(self):
        self.log(message="entering")
        try:
            return await self.lock.__aenter__()
        finally:
            self.log(message="entered")

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.log(message="exiting")
        try:
            return await self.lock.__aexit__(exc_type, exc_value, traceback)
        finally:
            self.log(message="exited")

    def log(self, message):
        self.logger.info(f" ==== {message} {self.id} (locked: {self.lock.locked()})")
        stack = "".join(traceback.format_stack())
        self.logger.info(stack)
