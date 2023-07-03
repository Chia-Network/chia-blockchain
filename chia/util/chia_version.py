from __future__ import annotations

from typing import Optional

from packaging.version import InvalidVersion, Version

from chia import __version__


def chia_version_str() -> str:
    return chia_version_str_from_version(Version(__version__))


def chia_version_str_from_version(version: Version) -> str:
    release_version_str = f"{version.major}.{version.minor}.{version.micro}"

    return release_version_str if version.pre is None else release_version_str + "".join(map(str, version.pre))


def chia_version_str_from_str(version: str) -> Optional[str]:
    try:
        return chia_version_str_from_version(Version(version))
    except InvalidVersion:
        return None
