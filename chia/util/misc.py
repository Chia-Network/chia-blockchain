def format_bytes(bytes: int) -> str:

    if not isinstance(bytes, int) or bytes < 0:
        return "Invalid"

    labels = {0: "MiB", 1: "GiB", 2: "TiB", 3: "PiB", 4: "EiB", 5: "ZiB", 6: "YiB"}

    base = 1024
    value = bytes / base ** 2
    key = 0
    while value >= base and key < 6:
        value /= base
        key += 1

    return f"{value:.3f} {labels[key]}"


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
