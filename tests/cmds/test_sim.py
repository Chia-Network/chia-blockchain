from __future__ import annotations

from pathlib import Path
from shutil import rmtree

import pytest
from click.testing import CliRunner

from chia.cmds.chia import cli
from chia.util.config import lock_and_load_config, save_config
from chia.util.default_root import SIMULATOR_ROOT_PATH

mnemonic = (  # ignore any secret warnings
    "cup smoke miss park baby say island tomorrow segment lava bitter easily settle gift renew arrive kangaroo dilemma "
    "organ skin design salt history awesome"
)
fingerprint = 2640131813
std_farming_address = "txch1mh4qanzyawn3v4uphgaj2cg6hrjazwyp0sx653fhn9apg6mfajlqtj0ztp"
burn_address = "txch1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqm6ksh7qddh"  # 0x0...dead

SIMULATOR_ROOT_PATH.mkdir(parents=True, exist_ok=True)  # this simplifies code later


def get_profile_path(starting_string: str) -> str:
    """
    Returns the name of a profile that does not exist yet.
    """
    i = 0
    while Path(SIMULATOR_ROOT_PATH / (starting_string + str(i))).exists():
        i += 1
    return starting_string + str(i)


def test_every_simulator_command() -> None:
    starting_str = "ci_test"
    simulator_name = get_profile_path(starting_str)
    runner: CliRunner = CliRunner()
    address = std_farming_address
    start_result = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "create", "-bm", mnemonic],
        catch_exceptions=False,
    )
    assert start_result.exit_code == 0
    assert f"Farming & Prefarm reward address: {address}" in start_result.output
    assert "chia_full_node_simulator: started" in start_result.output
    assert "Genesis block generated, exiting." in start_result.output

    config_dir = SIMULATOR_ROOT_PATH.joinpath(simulator_name)
    with lock_and_load_config(config_dir, "config.yaml") as config:
        config["rpc_timeout"] = 600
        save_config(config_dir, "config.yaml", config)

    try:
        # run all tests
        run_all_tests(runner, address, simulator_name)
    finally:
        stop_simulator(runner, simulator_name)


@pytest.mark.skip("Need to rewrite")
def test_custom_farming_address() -> None:
    runner: CliRunner = CliRunner()
    address = burn_address
    starting_str = "ci_address_test"
    simulator_name = get_profile_path(starting_str)
    start_result = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "create", "-bm", mnemonic, "--reward-address", address],
        catch_exceptions=False,
    )
    assert start_result.exit_code == 0
    assert f"Farming & Prefarm reward address: {address}" in start_result.output
    assert "chia_full_node_simulator: started" in start_result.output
    assert "Genesis block generated, exiting." in start_result.output

    try:
        # just run status test
        _test_sim_status(runner, address, simulator_name)
    finally:
        stop_simulator(runner, simulator_name)


def stop_simulator(runner: CliRunner, simulator_name: str) -> None:
    """Stop simulator."""
    result = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "stop", "-d"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "chia_full_node_simulator: Stopped\nDaemon stopped\n" == result.output
    rmtree(SIMULATOR_ROOT_PATH / simulator_name)


def run_all_tests(runner: CliRunner, address: str, simulator_name: str) -> None:
    """Run all tests."""
    _test_sim_status(runner, address, simulator_name)
    _test_farm_and_revert_block(runner, address, simulator_name)


def _test_sim_status(runner: CliRunner, address: str, simulator_name: str) -> None:
    # show everything
    result = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "status", "--show-key", "-cia"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    # asserts are grouped by arg
    assert (
        f"Fingerprint: {fingerprint}" in result.output
        and f"Mnemonic seed (24 secret words):\n{mnemonic}" in result.output
    )  # -k

    assert (
        "Network: simulator0" in result.output and "Current Blockchain Status: Full Node Synced" in result.output
    )  # default
    assert "Height:          1" in result.output  # default
    assert f"Current Farming address: {address}, with a balance of: 21000000.0 TXCH." in result.output  # default

    assert (
        f"Address: {address} has a balance of: 21000000000000000000 mojo, with a total of: 2 transactions."
        in result.output
    )  # -ia
    assert "Coin Amount: 2625000000000000000 mojo" in result.output  # -ic


def _test_farm_and_revert_block(runner: CliRunner, address: str, simulator_name: str) -> None:
    # make 5 blocks
    five_blocks_result = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "farm", "-b", "5", "-a", address],
        catch_exceptions=False,
    )
    assert five_blocks_result.exit_code == 0
    assert "Farmed 5 Transaction blocks" in five_blocks_result.output

    # check that height increased
    five_blocks_check = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "status"],
        catch_exceptions=False,
    )
    assert five_blocks_check.exit_code == 0
    assert "Height:          6" in five_blocks_check.output

    # do a reorg, 3 blocks back, 2 blocks forward, height now 8
    reorg_result = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "revert", "-b", "3", "-n", "2"],
        catch_exceptions=False,
    )
    assert reorg_result.exit_code == 0
    assert "Block: 3 and above " in reorg_result.output and "Block Height is now: 8" in reorg_result.output

    # check that height changed by 2
    reorg_check = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "status"],
        catch_exceptions=False,
    )
    assert reorg_check.exit_code == 0
    assert "Height:          8" in reorg_check.output

    # do a forceful reorg 4 blocks back
    forced_reorg_result = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "revert", "-b", "4", "-fd"],
        catch_exceptions=False,
    )
    assert forced_reorg_result.exit_code == 0
    assert (
        "Block: 8 and above were successfully deleted" in forced_reorg_result.output
        and "Block Height is now: 4" in forced_reorg_result.output
    )

    # check that height changed by 4
    forced_reorg_check = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "status"],
        catch_exceptions=False,
    )
    assert forced_reorg_check.exit_code == 0
    assert "Height:          4" in forced_reorg_check.output

    # test chain reset to genesis
    genesis_reset_result = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "revert", "-fd", "--reset"],
        catch_exceptions=False,
    )
    assert genesis_reset_result.exit_code == 0
    assert (
        "Block: 2 and above were successfully deleted" in genesis_reset_result.output
        and "Block Height is now: 1" in genesis_reset_result.output
    )

    # check that height changed to 1
    genesis_reset_check = runner.invoke(
        cli,
        ["dev", "sim", "-n", simulator_name, "status"],
        catch_exceptions=False,
    )
    assert genesis_reset_check.exit_code == 0
    assert "Height:          1" in genesis_reset_check.output
