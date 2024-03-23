from __future__ import annotations

from typing import Optional, Union

from packaging.version import InvalidVersion, Version

from chia import __version__


def _chia_short_version_from_version(version: Version) -> str:
    release_version_str = f"{version.major}.{version.minor}.{version.micro}"

    return release_version_str if version.pre is None else release_version_str + "".join(map(str, version.pre))


def chia_short_version(version: Optional[Union[str, Version]] = None) -> str:
    if version is None:
        return chia_short_version(__version__)

    if isinstance(version, Version):
        return _chia_short_version_from_version(version)

    try:
        return chia_short_version(Version(version))
    except InvalidVersion:
        return version
