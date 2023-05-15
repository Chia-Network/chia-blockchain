from __future__ import annotations

from pkg_resources import parse_version

def compare_version(ver1: str, ver2: str) -> int:
    normalized_ver1 = parse_version(ver1)
    normalized_ver2 = parse_version(ver2)
    if normalized_ver1 < normalized_ver2:
        return -1
    elif normalized_ver1 > normalized_ver2:
        return 1
    return 0
