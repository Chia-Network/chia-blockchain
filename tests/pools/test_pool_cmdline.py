# flake8: noqa: E501

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner, Result

from chia.cmds.plotnft import create_cmd, show_cmd, validate_fee

pytestmark = pytest.mark.skip("TODO: Works locally but fails on CI, needs to be fixed!")


class TestPoolNFTCommands:
    def test_validate_fee(self):
        with pytest.raises(click.exceptions.BadParameter):
            r = validate_fee(None, "fee", "1.0")

        with pytest.raises(click.exceptions.BadParameter):
            r = validate_fee(None, "fee", "-1")

        r = validate_fee(None, "fee", "0")
        assert r == "0"

        r = validate_fee(None, "fee", "0.000000000001")
        assert r == "0.000000000001"

        r = validate_fee(None, "fee", "0.5")
        assert r == "0.5"

    def test_plotnft_show(self):
        runner = CliRunner()
        result = runner.invoke(show_cmd, [], catch_exceptions=False)
        assert result.exit_code == 0

    def test_validate_fee_cmdline(self):
        runner = CliRunner()
        result = runner.invoke(create_cmd, ["create", "-s", "local", "--fee", "0.005"], catch_exceptions=False)
        assert result.exit_code != 0
