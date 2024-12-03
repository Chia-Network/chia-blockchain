from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import click
import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.capture import CaptureFixture

import chia._tests
from chia._tests.util.misc import Marks, datacases
from chia.cmds.gh import Per, TestCMD

test_root = Path(chia._tests.__file__).parent


@dataclass
class InvalidOnlyCase:
    only: Path
    per: Per
    exists: bool
    marks: Marks = ()

    @property
    def id(self) -> str:
        return f"{self.per}: {self.only}"


@datacases(
    InvalidOnlyCase(only=Path("does_not_exist.py"), per="directory", exists=False),
    InvalidOnlyCase(only=Path("pools/test_pool_rpc.py"), per="directory", exists=True),
    InvalidOnlyCase(only=Path("does_not_exist/"), per="file", exists=False),
    InvalidOnlyCase(only=Path("pools/"), per="file", exists=True),
)
@pytest.mark.anyio
async def test_invalid_only(case: InvalidOnlyCase) -> None:
    cmd = TestCMD(only=case.only, per=case.per)

    if case.exists:
        assert test_root.joinpath(case.only).exists()
        explanation = "wrong type"
        if case.per == "directory":
            assert test_root.joinpath(case.only).is_file()
        else:
            assert test_root.joinpath(case.only).is_dir()
    else:
        assert not test_root.joinpath(case.only).exists()
        explanation = "does not exist"

    with pytest.raises(click.ClickException, match=rf"\bto be a {re.escape(case.per)}\b.*\b{re.escape(explanation)}\b"):
        await cmd.run()


@pytest.mark.anyio
async def test_successfully_dispatches(
    capsys: CaptureFixture[str],
) -> None:
    cmd = TestCMD(
        # TODO: stop hardcoding here
        owner="chia-network",
        repository="chia-blockchain",
        per="file",
        only=Path("util/test_errors.py"),
        duplicates=2,
        oses=["linux", "macos-arm"],
        full_python_matrix=True,
        open_browser=False,
    )

    capsys.readouterr()
    await cmd.run()
    stdout, stderr = capsys.readouterr()

    assert len(stderr.strip()) == 0
    for line in stdout.splitlines():
        match = re.search(r"(?<=\brun url: )(?P<url>.*)", line)
        if match is None:
            continue
        url = match.group("url")
        break
    else:
        pytest.fail(f"Failed to find run url in: {stdout}")

    async with aiohttp.ClientSession(raise_for_status=True) as client:
        async with client.get(url):
            pass
