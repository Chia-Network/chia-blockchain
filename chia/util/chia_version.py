from __future__ import annotations

from re import search
from typing import Union

from packaging.version import InvalidVersion, Version

from chia import __version__


def _chia_short_version_from_version(version: Version) -> str:
    release_version_str = f"{version.major}.{version.minor}.{version.micro}"

    return release_version_str if version.pre is None else release_version_str + "".join(map(str, version.pre))


def _chia_short_version_from_str(version: str) -> str:
    try:
        return chia_short_version(Version(version))
    except InvalidVersion:
        pass
    match = search(r"^(\d+\.\d+\.\d+)", version)
    if match is not None:
        return match.group(1)

    return version


def chia_short_version(version: Union[str, Version] = __version__) -> str:
    if isinstance(version, Version):
        return _chia_short_version_from_version(version)

    return _chia_short_version_from_str(version)
