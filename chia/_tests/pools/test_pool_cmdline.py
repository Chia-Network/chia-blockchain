# flake8: noqa: E501

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner, Result

from chia.cmds.plotnft import create_cmd, show_cmd

pytestmark = pytest.mark.skip("TODO: Works locally but fails on CI, needs to be fixed!")


class TestPoolNFTCommands:
    def test_plotnft_show(self):
        runner = CliRunner()
        result = runner.invoke(show_cmd, [], catch_exceptions=False)
        assert result.exit_code == 0

    def test_validate_fee_cmdline(self):
        runner = CliRunner()
        result = runner.invoke(create_cmd, ["create", "-s", "local", "--fee", "0.005"], catch_exceptions=False)
        assert result.exit_code != 0
