from __future__ import annotations

from pathlib import Path
from typing import Any

import click
from click.testing import CliRunner

from chia._tests.cmds.wallet.test_consts import STD_TX
from chia.cmds.cmds_util import TransactionBundle, tx_out_cmd
from chia.wallet.transaction_record import TransactionRecord


def test_tx_out_cmd(tmp_path: Path) -> None:
    @click.command()
    @tx_out_cmd()
    def test_cmd(**kwargs: Any) -> list[TransactionRecord]:
        with open(tmp_path / "temp.push", "w") as file:
            file.write(str(kwargs["push"]))
        return [STD_TX, STD_TX]

    runner: CliRunner = CliRunner()
    runner.invoke(test_cmd, ["--transaction-file-out", str(tmp_path / "temp.transaction")])
    with open(tmp_path / "temp.transaction", "rb") as file:
        assert TransactionBundle.from_bytes(file.read()) == TransactionBundle([STD_TX, STD_TX])
    with open(tmp_path / "temp.push") as file2:
        assert file2.read() == "True"
