from __future__ import annotations

from typing import Optional

import pytest
from packaging.version import Version

from chia import __version__
from chia.util.chia_version import chia_version_str, chia_version_str_from_str, chia_version_str_from_version


@pytest.mark.parametrize(
    "version,result",
    [
        (Version("1.8.2rc3.dev116"), "1.8.2rc3"),
        (Version("2.0.0b1.dev3"), "2.0.0b1"),
        (Version("1.8.1.dev0"), "1.8.1"),
        (Version("1.0"), "1.0.0"),
        (Version("2.0"), "2.0.0"),
        (Version("2.0.0.1"), "2.0.0"),
        (Version("1.8.2+og-1.4.0"), "1.8.2"),
        (Version("1.8.2"), "1.8.2"),
    ],
)
def test_chia_version_str_from_version(version: Version, result: str) -> None:
    assert chia_version_str_from_version(version) == result


def test_chia_version_str() -> None:
    assert chia_version_str() == chia_version_str_from_version(Version(__version__))


@pytest.mark.parametrize(
    "version,result",
    [
        ("1.8.2rc3.dev116", "1.8.2rc3"),
        ("2.0.0b1.dev3", "2.0.0b1"),
        ("1.8.1.dev0", "1.8.1"),
        ("1.0", "1.0.0"),
        ("2.0", "2.0.0"),
        ("2.0.0.1", "2.0.0"),
        ("1.8.2+og-1.4.0", "1.8.2"),
        ("1.8.2", "1.8.2"),
        ("something", None),
    ],
)
def test_chia_version_str_from_str(version: str, result: Optional[str]) -> None:
    assert chia_version_str_from_str(version) == result
