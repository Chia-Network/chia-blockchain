from __future__ import annotations

from decimal import Decimal
from typing import Optional

import click

from chia.cmds import options

MAX_CMDLINE_FEE = Decimal(0.5)


def validate_fee(ctx: click.Context, param: click.Parameter, value: str) -> str:
    try:
        fee = Decimal(value)
    except ValueError:
        raise click.BadParameter("Fee must be decimal dotted value in XCH (e.g. 0.00005)")
    if fee < 0 or fee > MAX_CMDLINE_FEE:
        raise click.BadParameter(f"Fee must be in the range 0 to {MAX_CMDLINE_FEE}")
    return value


@click.group("plotnft", help="Manage your plot NFTs")
def plotnft_cmd() -> None:
    pass


@plotnft_cmd.command("show", help="Show plotnft information")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-i", "--id", help="ID of the wallet to use", type=int, default=None, show_default=True, required=False)
@options.create_fingerprint()
def show_cmd(wallet_rpc_port: Optional[int], fingerprint: int, id: int) -> None:
    import asyncio

    from .plotnft_funcs import show

    asyncio.run(show(wallet_rpc_port, fingerprint, id))


@plotnft_cmd.command("get_login_link", help="Create a login link for a pool. To get the launcher id, use plotnft show.")
@click.option("-l", "--launcher_id", help="Launcher ID of the plotnft", type=str, required=True)
def get_login_link_cmd(launcher_id: str) -> None:
    import asyncio

    from .plotnft_funcs import get_login_link

    asyncio.run(get_login_link(launcher_id))


@plotnft_cmd.command("create", help="Create a plot NFT")
@click.option("-y", "--yes", "dont_prompt", help="No prompts", is_flag=True)
@options.create_fingerprint()
@click.option("-u", "--pool_url", help="HTTPS host:port of the pool to join", type=str, required=False)
@click.option("-s", "--state", help="Initial state of Plot NFT: local or pool", type=str, required=True)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH. Fee is used TWICE: once to create the singleton, once for init.",
    type=str,
    default="0",
    show_default=True,
    required=True,
    callback=validate_fee,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
def create_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    pool_url: str,
    state: str,
    fee: str,
    dont_prompt: bool,
) -> None:
    import asyncio

    from .plotnft_funcs import create

    if pool_url is not None and state.lower() == "local":
        print(f"  pool_url argument [{pool_url}] is not allowed when creating in 'local' state")
        return
    if pool_url in [None, ""] and state.lower() == "pool":
        print("  pool_url argument (-u) is required for pool starting state")
        return
    valid_initial_states = {"pool": "FARMING_TO_POOL", "local": "SELF_POOLING"}
    asyncio.run(create(wallet_rpc_port, fingerprint, pool_url, valid_initial_states[state], Decimal(fee), dont_prompt))


@plotnft_cmd.command("join", help="Join a plot NFT to a Pool")
@click.option("-y", "--yes", "dont_prompt", help="No prompts", is_flag=True)
@click.option("-i", "--id", help="ID of the wallet to use", type=int, default=None, show_default=True, required=True)
@options.create_fingerprint()
@click.option("-u", "--pool_url", help="HTTPS host:port of the pool to join", type=str, required=True)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH. Fee is used TWICE: once to leave pool, once to join.",
    type=str,
    default="0",
    show_default=True,
    required=True,
    callback=validate_fee,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
def join_cmd(
    wallet_rpc_port: Optional[int], fingerprint: int, id: int, fee: int, pool_url: str, dont_prompt: bool
) -> None:
    import asyncio

    from .plotnft_funcs import join_pool

    asyncio.run(
        join_pool(
            wallet_rpc_port=wallet_rpc_port,
            fingerprint=fingerprint,
            pool_url=pool_url,
            fee=Decimal(fee),
            wallet_id=id,
            prompt=dont_prompt,
        )
    )


@plotnft_cmd.command("leave", help="Leave a pool and return to self-farming")
@click.option("-y", "--yes", "dont_prompt", help="No prompts", is_flag=True)
@click.option("-i", "--id", help="ID of the wallet to use", type=int, default=None, show_default=True, required=True)
@options.create_fingerprint()
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH. Fee is charged TWICE.",
    type=str,
    default="0",
    show_default=True,
    required=True,
    callback=validate_fee,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
def self_pool_cmd(wallet_rpc_port: Optional[int], fingerprint: int, id: int, fee: int, dont_prompt: bool) -> None:
    import asyncio

    from .plotnft_funcs import self_pool

    asyncio.run(
        self_pool(
            wallet_rpc_port=wallet_rpc_port,
            fingerprint=fingerprint,
            fee=Decimal(fee),
            wallet_id=id,
            prompt=dont_prompt,
        )
    )


@plotnft_cmd.command("inspect", help="Get Detailed plotnft information as JSON")
@click.option("-i", "--id", help="ID of the wallet to use", type=int, default=None, show_default=True, required=True)
@options.create_fingerprint()
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
def inspect(wallet_rpc_port: Optional[int], fingerprint: int, id: int) -> None:
    import asyncio

    from .plotnft_funcs import inspect_cmd

    asyncio.run(inspect_cmd(wallet_rpc_port, fingerprint, id))


@plotnft_cmd.command("claim", help="Claim rewards from a plot NFT")
@click.option("-i", "--id", help="ID of the wallet to use", type=int, default=None, show_default=True, required=True)
@options.create_fingerprint()
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    required=True,
    callback=validate_fee,
)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
def claim(wallet_rpc_port: Optional[int], fingerprint: int, id: int, fee: int) -> None:
    import asyncio

    from .plotnft_funcs import claim_cmd

    asyncio.run(
        claim_cmd(
            wallet_rpc_port=wallet_rpc_port,
            fingerprint=fingerprint,
            fee=Decimal(fee),
            wallet_id=id,
        )
    )


@plotnft_cmd.command(
    "change_payout_instructions",
    help="Change the payout instructions for a pool. To get the launcher id, use plotnft show.",
)
@click.option("-l", "--launcher_id", help="Launcher ID of the plotnft", type=str, required=True)
@click.option("-a", "--address", help="New address for payout instructions", type=str, required=True)
def change_payout_instructions_cmd(launcher_id: str, address: str) -> None:
    import asyncio

    from .plotnft_funcs import change_payout_instructions

    asyncio.run(change_payout_instructions(launcher_id, address))
