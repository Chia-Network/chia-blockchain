import click


@click.group("poolnft", short_help="Manage your pool NFTs")
def poolnft_cmd() -> None:
    pass


@poolnft_cmd.command("show", short_help="Show poolnft information")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-i", "--id", help="Id of the wallet to use", type=int, default=None, show_default=True, required=False)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
def show_cmd(wallet_rpc_port: int, fingerprint: int, id: int) -> None:
    import asyncio
    from .wallet_funcs import execute_with_wallet
    from .poolnft_funcs import show

    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, {"id": id}, show))


@poolnft_cmd.command("create", short_help="Create a pool NFT")
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which wallet to use", type=int)
@click.option("-u", "--pool_url", help="HTTPS host:port of the pool to join", type=str, required=True)
def create_cmd(wallet_rpc_port: int, fingerprint: int, pool_url: str) -> None:
    import asyncio
    from .wallet_funcs import execute_with_wallet
    from .poolnft_funcs import create

    extra_params = {"pool_url": pool_url}
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, create))
