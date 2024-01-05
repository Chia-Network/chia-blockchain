from __future__ import annotations

import os
import pathlib

import pytest

import chia


@pytest.mark.skipif(condition=os.environ.get("CI") is None, reason="Skip outside CI")
def test_chia_installed() -> None:
    assert "venv" in pathlib.Path(chia.__file__).parts
