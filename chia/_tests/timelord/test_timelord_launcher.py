from __future__ import annotations

from pathlib import Path

import chiavdf
import pytest

from chia.timelord.timelord_launcher import find_vdf_client


@pytest.mark.parametrize(
    ("locations", "expected"),
    [
        (("pkg",), "pkg"),
        (("root",), "root"),
        (("pkg", "root"), "pkg"),
        ((), None),
    ],
)
def test_find_vdf_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    locations: tuple[str, ...],
    expected: str | None,
) -> None:
    site_packages = tmp_path / "site-packages"
    pkg = site_packages / "chiavdf"
    pkg.mkdir(parents=True)
    monkeypatch.setattr(chiavdf, "__file__", str(pkg / "__init__.py"))
    for location in locations:
        (pkg if location == "pkg" else site_packages).joinpath("vdf_client").write_text("")
    if expected is None:
        with pytest.raises(FileNotFoundError):
            find_vdf_client()
    else:
        assert find_vdf_client() == (pkg if expected == "pkg" else site_packages) / "vdf_client"
