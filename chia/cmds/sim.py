from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

import click

from chia.cmds.sim_funcs import async_config_wizard, farm_blocks, print_status, revert_block_height, set_auto_farm
from chia.util.default_root import SIMULATOR_ROOT_PATH


@click.group("sim", help="Configure and make requests to a Chia Simulator Full Node")
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Simulator is hosting the RPC interface. "
        "See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
)
@click.option(
    "--root-path", default=SIMULATOR_ROOT_PATH, help="Simulator root folder.", type=click.Path(), show_default=True
)
@click.option(
    "-n",
    "--simulator-name",
    help="This name is used to determine the sub folder to use in the simulator root folder.",
    type=str,
    default="main",
)
@click.pass_context
def sim_cmd(ctx: click.Context, rpc_port: Optional[int], root_path: str, simulator_name: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["root_path"] = Path(root_path) / simulator_name
    ctx.obj["sim_name"] = simulator_name
    ctx.obj["rpc_port"] = rpc_port


@sim_cmd.command("create", help="Guides you through the process of setting up a Chia Simulator")
@click.option("-f", "--fingerprint", type=int, required=False, help="Use your fingerprint to skip the key prompt")
@click.option(
    "-r",
    "--reward-address",
    type=str,
    required=False,
    help="Use this address instead of the default farming address.",
)
@click.option(
    "-p", "--plot-directory", type=str, required=False, help="Use a different directory then 'simulator/plots'."
)
@click.option("-m", "--mnemonic", type=str, required=False, help="Add to keychain and use a specific mnemonic.")
@click.option("-a", "--auto-farm", type=bool, default=None, help="Enable or Disable auto farming")
@click.option(
    "-d",
    "--docker-mode",
    is_flag=True,
    hidden=True,
    help="Run non-interactively in Docker Mode, & generate a new key if keychain is empty.",
)
@click.option("-b", "--no-bitfield", type=bool, is_flag=True, help="Do not use bitfield when generating plots")
@click.pass_context
def create_simulator_config(
    ctx: click.Context,
    fingerprint: Optional[int],
    reward_address: Optional[str],
    plot_directory: Optional[str],
    mnemonic: Optional[str],
    auto_farm: Optional[bool],
    docker_mode: bool,
    no_bitfield: bool,
) -> None:
    print(f"Using this Directory: {ctx.obj['root_path']}\n")
    if fingerprint and mnemonic:
        print("You can't use both a fingerprint and a mnemonic. Please choose one.")
        return None
    asyncio.run(
        async_config_wizard(
            ctx.obj["root_path"],
            fingerprint,
            reward_address,
            plot_directory,
            mnemonic,
            auto_farm,
            docker_mode,
            not no_bitfield,
        )
    )


@sim_cmd.command("start", help="Start service groups while automatically using the right chia_root.")
@click.option("-r", "--restart", is_flag=True, help="Restart running services")
@click.option("-w", "--wallet", is_flag=True, help="Start wallet")
@click.pass_context
def sim_start_cmd(ctx: click.Context, restart: bool, wallet: bool) -> None:
    from chia.cmds.start import start_cmd

    group: tuple[str, ...] = ("simulator",)
    if wallet:
        group += ("wallet",)
    ctx.invoke(start_cmd, restart=restart, group=group)


@sim_cmd.command("stop", help="Stop running services while automatically using the right chia_root.")
@click.option("-d", "--daemon", is_flag=True, help="Stop daemon")
@click.option("-w", "--wallet", is_flag=True, help="Stop wallet")
@click.pass_context
def sim_stop_cmd(ctx: click.Context, daemon: bool, wallet: bool) -> None:
    from chia.cmds.stop import stop_cmd

    group: Any = ("simulator",)
    if wallet:
        group += ("wallet",)
    ctx.invoke(stop_cmd, daemon=daemon, group=group)


@sim_cmd.command("status", help="Get information about the state of the simulator.")
@click.option("-f", "--fingerprint", type=int, help="Get detailed information on this fingerprint.")
@click.option("--show-key/--no-show-key", help="Show detailed key information.")
@click.option("-c", "--show-coins", is_flag=True, help="Show all unspent coins.")
@click.option("-i", "--include-rewards", is_flag=True, help="Include reward coins when showing coins.")
@click.option("-a", "--show-addresses", is_flag=True, help="Show the balances of all addresses.")
@click.pass_context
def status_cmd(
    ctx: click.Context,
    fingerprint: Optional[int],
    show_key: bool,
    show_coins: bool,
    include_rewards: bool,
    show_addresses: bool,
) -> None:
    asyncio.run(
        print_status(
            ctx.obj["rpc_port"],
            ctx.obj["root_path"],
            fingerprint,
            show_key,
            show_coins,
            include_rewards,
            show_addresses,
        )
    )


@sim_cmd.command("revert", help="Reset chain to a previous block height.")
@click.option("-b", "--blocks", type=int, default=1, help="Number of blocks to go back.")
@click.option("-n", "--new-blocks", type=int, default=1, help="Number of new blocks to add during a reorg.")
@click.option("-r", "--reset", is_flag=True, help="Reset the chain to the genesis block")
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Forcefully delete blocks, this is not a reorg but might be needed in very special circumstances."
    "  Note: Use with caution, this will break all wallets.",
)
@click.option("-d", "--disable-prompt", is_flag=True, help="Disable confirmation prompt when force reverting.")
@click.pass_context
def revert_cmd(
    ctx: click.Context, blocks: int, new_blocks: int, reset: bool, force: bool, disable_prompt: bool
) -> None:
    if force and not disable_prompt:
        input_str = (
            "Are you sure you want to force delete blocks? This should only ever be used in special circumstances,"
            " and will break all wallets. \nPress 'y' to continue, or any other button to exit: "
        )
        if input(input_str) != "y":
            return
    if reset and not force:
        print("\n The force flag (-f) is required to reset the chain to the genesis block. \n")
        return
    if reset and blocks != 1:
        print("\nBlocks, '-b' must not be set if all blocks are selected by reset, '-r'. Exiting.\n")
        return
    asyncio.run(
        revert_block_height(
            ctx.obj["rpc_port"],
            ctx.obj["root_path"],
            blocks,
            new_blocks,
            reset,
            force,
        )
    )


@sim_cmd.command("farm", help="Farm blocks")
@click.option("-b", "--blocks", type=int, default=1, help="Amount of blocks to create")
@click.option("-n", "--non-transaction", is_flag=True, help="Allow non-transaction blocks")
@click.option("-a", "--target-address", type=str, default="", help="Block reward address")
@click.pass_context
def farm_cmd(ctx: click.Context, blocks: int, non_transaction: bool, target_address: str) -> None:
    asyncio.run(
        farm_blocks(
            ctx.obj["rpc_port"],
            ctx.obj["root_path"],
            blocks,
            not non_transaction,
            target_address,
        )
    )


@sim_cmd.command("autofarm", help="Enable or disable auto farming on transaction submission")
@click.argument("set-autofarm", type=click.Choice(["on", "off"]), nargs=1, required=True)
@click.pass_context
def autofarm_cmd(ctx: click.Context, set_autofarm: str) -> None:
    autofarm = bool(set_autofarm == "on")
    asyncio.run(
        set_auto_farm(
            ctx.obj["rpc_port"],
            ctx.obj["root_path"],
            autofarm,
        )
    )
