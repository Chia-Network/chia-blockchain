# flake8: noqa: E501

import click
import pytest
from click.testing import CliRunner, Result

from chia.cmds.plotnft import validate_fee
from chia.cmds.plotnft import create_cmd, show_cmd


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
        result: Result = runner.invoke(show_cmd, [])
        assert result.exit_code == 0

    def test_validate_fee_cmdline(self):
        runner = CliRunner()
        result: Result = runner.invoke(create_cmd, ["create", "-s", "local", "--fee", "0.005"])
        assert result.exit_code != 0
