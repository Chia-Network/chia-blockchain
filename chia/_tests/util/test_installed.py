from __future__ import annotations

import os
import pathlib

import pytest

import chia


@pytest.mark.skipif(condition=os.environ.get("CI") is None, reason="Skip outside CI")
def test_chia_installed() -> None:
    """This checks that the in-memory chia package was loaded from an installed copy
    and not the not-installed source code.  This is relevant because it makes our
    tests exercise the code and support files from our wheel which can differ from
    the source.  We have missed some source files and also some data files in the past
    and testing the installed code checks for that.  A next step would be to install
    using the actual wheel file we are going to publish.
    """
    assert ".venv" in pathlib.Path(chia.__file__).parts
