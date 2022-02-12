import sys
from typing import Optional
import asyncio
import click


@click.group("get", short_help="Get information stored on the blockchain")
def get_cmd() -> None:
    pass


@get_cmd.command("transactions", short_help="Get all transactions for a specific address.")
@click.option(
    "-a",
    "--address",
    help="The address to use for the search.",
    type=str,
    required=True,
)
@click.option(
    "-np",
    "--node-rpc-port",
    help="Set the port where the Full node is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option(
    "-o",
    "--offset",
    help="Skip transactions from the beginning of the list",
    type=int,
    default=0,
    show_default=True,
    required=True,
)
@click.option("--verbose", "-v", count=True, type=int)
@click.option(
    "--paginate/--no-paginate",
    default=None,
    help="Prompt for each page of data.  Defaults to true for interactive consoles, otherwise false.",
)
def get_transactions_using_address(
    address: str,
    node_rpc_port: Optional[int],
    offset: int,
    verbose: bool,
    paginate: Optional[bool],
) -> None:
    try:
        from chia.util.bech32m import decode_puzzle_hash

        ph = decode_puzzle_hash(address)
    except ValueError:
        print("Invalid address")
        sys.exit(1)
    extra_params = {"verbose": verbose, "offset": offset, "paginate": paginate, "ph": ph}
    from chia.cmds.get_funcs import execute_with_node
    from chia.cmds.get_funcs import get_transactions

    asyncio.run(execute_with_node(node_rpc_port, extra_params, get_transactions))

    # The flush/close avoids output like below when piping through `head -n 1`
    # which will close stdout.
    #
    # Exception ignored in: <_io.TextIOWrapper name='<stdout>' mode='w' encoding='utf-8'>
    # BrokenPipeError: [Errno 32] Broken pipe
    sys.stdout.flush()
    sys.stdout.close()
