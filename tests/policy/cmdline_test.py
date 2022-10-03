from __future__ import annotations

import os
from typing import Tuple, Union

from click.testing import CliRunner

from chia.cmds.chia import cli
from chia.full_node.full_node_api import FullNodeAPI
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator


def test_print_fee_info_cmd(
    one_node_one_block: Tuple[Union[FullNodeAPI, FullNodeSimulator], ChiaServer, BlockTools]
) -> None:
    _, _, _ = one_node_one_block
    exit_code = os.system("chia show -f")
    assert exit_code == 0


def test_show_fee_info(
    one_node_one_block: Tuple[Union[FullNodeAPI, FullNodeSimulator], ChiaServer, BlockTools]
) -> None:
    _, _, _ = one_node_one_block
    runner = CliRunner()
    result = runner.invoke(cli, ["show", "-f"])
    assert result.exit_code == 0
