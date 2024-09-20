from __future__ import annotations

from typing import Any, List

import click
from click.testing import CliRunner

from chia._tests.cmds.wallet.test_consts import STD_TX
from chia.cmds.cmds_util import TransactionBundle, tx_out_cmd
from chia.wallet.transaction_record import TransactionRecord


def test_tx_out_cmd() -> None:
    @click.command()
    @tx_out_cmd()
    def test_cmd(**kwargs: Any) -> List[TransactionRecord]:
        with open("./temp.push", "w") as file:
            file.write(str(kwargs["push"]))
        return [STD_TX, STD_TX]

    runner: CliRunner = CliRunner()
    with runner.isolated_filesystem():
        runner.invoke(test_cmd, ["--transaction-file", "./temp.transaction"])
        with open("./temp.transaction", "rb") as file:
            assert TransactionBundle.from_bytes(file.read()) == TransactionBundle([STD_TX, STD_TX])
        with open("./temp.push") as file2:
            assert file2.read() == "True"
