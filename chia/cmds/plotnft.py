import click


@click.group("plotnft", short_help="Manage your plot NFTs")
def plotnft_cmd() -> None:
    pass


@plotnft_cmd.command("show", short_help="Show plotnft information")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-i", "--id", help="ID of the wallet to use", type=int, default=None, show_default=True, required=False)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
def show_cmd(wallet_rpc_port: int, fingerprint: int, id: int) -> None:
    import asyncio
    from .wallet_funcs import execute_with_wallet
    from .plotnft_funcs import show

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, {"id": id}, show))


@plotnft_cmd.command(
    "get_login_link", short_help="Create a login link for a pool. To get the launcher id, use plotnft show."
)
@click.option("-l", "--launcher_id", help="Launcher ID of the plotnft", type=str, required=True)
def get_login_link_cmd(launcher_id: str) -> None:
    import asyncio
    from .plotnft_funcs import get_login_link

    asyncio.run(get_login_link(launcher_id))


@plotnft_cmd.command("create", short_help="Create a plot NFT")
@click.option("-y", "--yes", help="No prompts", is_flag=True)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-u", "--pool_url", help="HTTPS host:port of the pool to join", type=str, required=False)
@click.option("-s", "--state", help="Initial state of Plot NFT: local or pool", type=str, required=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
def create_cmd(wallet_rpc_port: int, fingerprint: int, pool_url: str, state: str, yes: bool) -> None:
    import asyncio
    from .wallet_funcs import execute_with_wallet
    from .plotnft_funcs import create

    if pool_url is not None and state.lower() == "local":
        print(f"  pool_url argument [{pool_url}] is not allowed when creating in 'local' state")
        return
    if pool_url in [None, ""] and state.lower() == "pool":
        print("  pool_url argument (-u) is required for pool starting state")
        return
    valid_initial_states = {"pool": "FARMING_TO_POOL", "local": "SELF_POOLING"}
    extra_params = {"pool_url": pool_url, "state": valid_initial_states[state], "yes": yes}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, create))


@plotnft_cmd.command("join", short_help="Join a plot NFT to a Pool")
@click.option("-y", "--yes", help="No prompts", is_flag=True)
@click.option("-i", "--id", help="ID of the wallet to use", type=int, default=None, show_default=True, required=True)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-u", "--pool_url", help="HTTPS host:port of the pool to join", type=str, required=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
def join_cmd(wallet_rpc_port: int, fingerprint: int, id: int, pool_url: str, yes: bool) -> None:
    import asyncio
    from .wallet_funcs import execute_with_wallet
    from .plotnft_funcs import join_pool

    extra_params = {"pool_url": pool_url, "id": id, "yes": yes}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, join_pool))


@plotnft_cmd.command("leave", short_help="Leave a pool and return to self-farming")
@click.option("-y", "--yes", help="No prompts", is_flag=True)
@click.option("-i", "--id", help="ID of the wallet to use", type=int, default=None, show_default=True, required=True)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
def self_pool_cmd(wallet_rpc_port: int, fingerprint: int, id: int, yes: bool) -> None:
    import asyncio
    from .wallet_funcs import execute_with_wallet
    from .plotnft_funcs import self_pool

    extra_params = {"id": id, "yes": yes}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, self_pool))


@plotnft_cmd.command("inspect", short_help="Get Detailed plotnft information as JSON")
@click.option("-i", "--id", help="ID of the wallet to use", type=int, default=None, show_default=True, required=True)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
def inspect(wallet_rpc_port: int, fingerprint: int, id: int) -> None:
    import asyncio
    from .wallet_funcs import execute_with_wallet
    from .plotnft_funcs import inspect_cmd

    extra_params = {"id": id}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, inspect_cmd))


@plotnft_cmd.command("claim", short_help="Claim rewards from a plot NFT")
@click.option("-i", "--id", help="ID of the wallet to use", type=int, default=None, show_default=True, required=True)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
def claim(wallet_rpc_port: int, fingerprint: int, id: int) -> None:
    import asyncio
    from .wallet_funcs import execute_with_wallet
    from .plotnft_funcs import claim_cmd

    extra_params = {"id": id}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, claim_cmd))
