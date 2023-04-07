from __future__ import annotations

import dataclasses
import signal
import sys
from pathlib import Path
from typing import Any, Dict, Sequence, Union

from chia.util.errors import InvalidPathError
from chia.util.ints import uint16
from chia.util.streamable import Streamable, recurse_jsonify, streamable


@streamable
@dataclasses.dataclass(frozen=True)
class VersionedBlob(Streamable):
    version: uint16
    blob: bytes


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


def prompt_yes_no(prompt: str) -> bool:
    while True:
        response = str(input(prompt + " (y/n): ")).lower().strip()
        ch = response[:1]
        if ch == "y":
            return True
        elif ch == "n":
            return False


def get_list_or_len(list_in: Sequence[object], length: bool) -> Union[int, Sequence[object]]:
    return len(list_in) if length else list_in


def dataclass_to_json_dict(instance: Any) -> Dict[str, Any]:
    ret: Dict[str, Any] = recurse_jsonify(instance)
    return ret


def validate_directory_writable(path: Path) -> None:
    write_test_path = path / ".write_test"
    try:
        with write_test_path.open("w"):
            pass
        write_test_path.unlink()
    except FileNotFoundError:
        raise InvalidPathError(path, "Directory doesn't exist")
    except OSError:
        raise InvalidPathError(path, "Directory not writable")


if sys.platform == "win32" or sys.platform == "cygwin":
    termination_signals = [signal.SIGBREAK, signal.SIGINT, signal.SIGTERM]
    sendable_termination_signals = [signal.SIGTERM]
else:
    termination_signals = [signal.SIGINT, signal.SIGTERM]
    sendable_termination_signals = termination_signals
