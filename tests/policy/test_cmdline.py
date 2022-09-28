import os
from click.testing import CliRunner
from chia.cmds.chia import cli


def test_print_fee_info_cmd(one_node_one_block) -> None:
    full_node_1, server_1, bt = one_node_one_block
    exit_code = os.system("chia show -f")
    assert exit_code == 0


def test_show_fee_info(one_node_one_block) -> None:
    full_node_1, server_1, bt = one_node_one_block
    runner = CliRunner()
    result = runner.invoke(cli, ['show', '-f'])
    assert result.exit_code == 0
