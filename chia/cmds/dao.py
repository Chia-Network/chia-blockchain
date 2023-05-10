from __future__ import annotations

from typing import Optional

import click

from chia.cmds.cmds_util import execute_with_wallet
from chia.cmds.plotnft import validate_fee


@click.group("dao", short_help="Create, manage or show state of DAOs", no_args_is_help=True)
@click.pass_context
def dao_cmd(ctx: click.Context) -> None:
    pass


# ----------------------------------------------------------------------------------------
# ADD


@dao_cmd.command("add", short_help="Create a wallet for an existing DAO", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-n", "--name", help="Set the DAO wallet name", type=str)
@click.option(
    "-t",
    "--treasury-id",
    help="The Treasury ID of the DAO you want to track",
    type=str,
    required=True,
)
@click.option(
    "-fa",
    "--filter-amount",
    help="The minimum number of votes a proposal needs before the wallet will recognise it",
    type=int,
    default=1,
    show_default=True,
)
def dao_add_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    treasury_id: str,
    filter_amount: int,
    name: Optional[str],
) -> None:
    import asyncio

    from .dao_funcs import add_dao_wallet

    extra_params = {
        "name": name,
        "treasury_id": treasury_id,
        "filter_amount": filter_amount,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, add_dao_wallet))


# ----------------------------------------------------------------------------------------
# CREATE


@dao_cmd.command("create", short_help="Create a new DAO wallet and treasury", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-n", "--name", help="Set the DAO wallet name", type=str)
@click.option(
    "-pt",
    "--proposal-timelock",
    help="The minimum number of blocks before a proposal can close",
    type=int,
    default=1000,
    show_default=True,
)
@click.option(
    "-sc",
    "--soft-close",
    help="The number of blocks a proposal must remain unspent before closing",
    type=int,
    default=20,
    show_default=True,
)
@click.option(
    "-ar",
    "--attendance-required",
    help="The minimum number of votes a proposal must receive to be accepted",
    type=int,
    required=True,
)
@click.option(
    "-pp",
    "--pass-percentage",
    help="The percentage of 'yes' votes in basis points a proposal must receive to be accepted. 100% = 10000",
    type=int,
    default=5000,
    show_default=True,
)
@click.option(
    "-sd",
    "--self-destruct",
    help="The number of blocks required before a proposal can be automatically removed",
    type=int,
    default=10000,
    show_default=True,
)
@click.option(
    "-od",
    "--oracle-delay",
    help="The number of blocks required between oracle spends of the treasury",
    type=int,
    default=50,
    show_default=True,
)
@click.option(
    "-fa",
    "--filter-amount",
    help="The minimum number of votes a proposal needs before the wallet will recognise it",
    type=int,
    default=1,
    show_default=True,
)
@click.option(
    "-ca",
    "--cat-amount",
    help="The number of DAO CATs (in mojos) to create when initializing the DAO",
    type=int,
    required=True,
)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def dao_create_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    proposal_timelock: int,
    soft_close: int,
    attendance_required: int,
    pass_percentage: int,
    self_destruct: int,
    oracle_delay: int,
    filter_amount: int,
    cat_amount: int,
    name: Optional[str],
    fee: Optional[int],
) -> None:
    import asyncio

    from .dao_funcs import create_dao_wallet

    print("Creating new DAO")

    extra_params = {
        "fee": fee,
        "name": name,
        "proposal_timelock": proposal_timelock,
        "soft_close_length": soft_close,
        "attendance_required": attendance_required,
        "pass_percentage": pass_percentage,
        "self_destruct_length": self_destruct,
        "oracle_spend_delay": oracle_delay,
        "filter_amount": filter_amount,
        "amount_of_cats": cat_amount,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, create_dao_wallet))


# ----------------------------------------------------------------------------------------
# TREASURY FUNDS


@dao_cmd.command("add-funds", short_help="Send funds to a DAO treasury", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
@click.option(
    "-f",
    "--funding-wallet-id",
    help="The ID of the wallet to send funds from",
    type=int,
    required=True,
)
@click.option(
    "-a",
    "--amount",
    help="The amount of funds to send",
    type=int,
    required=True,
)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def dao_add_funds_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    funding_wallet_id: int,
    amount: int,
    fee: Optional[int],
) -> None:
    import asyncio

    from .dao_funcs import add_funds_to_treasury

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "funding_wallet_id": funding_wallet_id,
        "amount": amount,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, add_funds_to_treasury))


@dao_cmd.command("get-balance", short_help="Get the asset balances for a DAO treasury", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
def dao_get_balance_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
) -> None:
    import asyncio

    from .dao_funcs import get_treasury_balance

    extra_params = {
        "wallet_id": wallet_id,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, get_treasury_balance))


# ----------------------------------------------------------------------------------------
# LIST/SHOW PROPOSALS


@dao_cmd.command("list-proposals", short_help="List proposals for the DAO", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
@click.option(
    "-c",
    "--include-closed",
    help="Include previously closed proposals",
    is_flag=True,
)
def dao_list_proposals_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    include_closed: Optional[bool],
) -> None:
    import asyncio

    from .dao_funcs import list_proposals

    if not include_closed:
        include_closed = False

    extra_params = {
        "wallet_id": wallet_id,
        "include_closed": include_closed,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, list_proposals))


@dao_cmd.command("show-proposal", short_help="Show the details of a specific proposal", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
@click.option(
    "-p",
    "--proposal_id",
    help="The ID of the proposal to fetch",
    type=str,
    required=True,
)
def dao_show_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    proposal_id: str,
) -> None:
    import asyncio

    from .dao_funcs import show_proposal

    extra_params = {
        "wallet_id": wallet_id,
        "proposal_id": proposal_id,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, show_proposal))


# ----------------------------------------------------------------------------------------
# VOTE


@dao_cmd.command("vote", short_help="Vote on a DAO proposal", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
@click.option(
    "-p",
    "--proposal-id",
    help="The ID of the proposal you are voting on",
    type=str,
    required=True,
)
@click.option(
    "-a",
    "--vote-amount",
    help="The number of votes you want to cast",
    type=int,
    required=True,
)
@click.option(
    "-n",
    "--vote-no",
    help="Use this option to vote against a proposal. If not present then the vote is for the proposal",
    is_flag=True,
)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def dao_vote_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    proposal_id: str,
    amount: int,
    vote_no: Optional[bool],
    fee: Optional[int],
) -> None:
    import asyncio

    from .dao_funcs import vote_on_proposal

    is_yes_vote = False if vote_no else True

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "proposal_id": proposal_id,
        "vote_amount": amount,
        "is_yes_vote": is_yes_vote,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, vote_on_proposal))


# ----------------------------------------------------------------------------------------
# CLOSE PROPOSALS


@dao_cmd.command("close-proposal", short_help="Close a DAO proposal", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
@click.option(
    "-p",
    "--proposal-id",
    help="The ID of the proposal you are voting on",
    type=str,
    required=True,
)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def dao_close_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    proposal_id: str,
    fee: Optional[int],
) -> None:
    import asyncio

    from .dao_funcs import close_proposal

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "proposal_id": proposal_id,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, close_proposal))


# ----------------------------------------------------------------------------------------
# LOCKUP COINS


@dao_cmd.command("lockup-coins", short_help="Lock DAO CATs for voting", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
@click.option(
    "-a",
    "--amount",
    help="The amount of new cats the proposal will mint",
    type=int,
    required=True,
)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def dao_lockup_coins_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    amount: int,
    fee: Optional[int],
) -> None:
    import asyncio

    from .dao_funcs import lockup_coins

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "amount": amount,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, lockup_coins))


@dao_cmd.command("release-coins", short_help="Release DAO CATs from voting mode", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def dao_release_coins_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    fee: Optional[int],
) -> None:
    import asyncio

    from .dao_funcs import release_coins

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, release_coins))


# ----------------------------------------------------------------------------------------
# CREATE PROPOSALS


@dao_cmd.group("create-proposal", short_help="Create and add a proposal to a DAO", no_args_is_help=True)
@click.pass_context
def dao_proposal(ctx: click.Context) -> None:
    pass


@dao_proposal.command("spend", short_help="Create a proposal to spend DAO funds", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
@click.option(
    "-t",
    "--to-address",
    help="The address the proposal will send funds to",
    type=str,
    required=False,
    default=None,
)
@click.option(
    "-a",
    "--amount",
    help="The amount of funds the proposal will send",
    type=float,
    required=False,
    default=None,
)
@click.option(
    "-id",
    "--asset-id",
    help="The asset id of the funds the proposal will send. Leave blank for xch",
    type=str,
    required=False,
    default=None,
)
@click.option(
    "-j",
    "--from-json",
    help="Path to a json file containing a list of additions, for use in proposals with multiple spends",
    type=str,
    required=False,
    default=None,
)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def dao_create_spend_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    to_address: Optional[str],
    amount: Optional[float],
    asset_id: Optional[str],
    from_json: Optional[str],
    fee: Optional[int],
) -> None:
    import asyncio

    from .dao_funcs import create_spend_proposal

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "to_address": to_address,
        "amount": amount,
        "asset_id": asset_id,
        "from_json": from_json,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, create_spend_proposal))


@dao_proposal.command("update", short_help="Create a proposal to change the DAO rules", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
@click.option(
    "-pt",
    "--proposal-timelock",
    help="The new minimum number of blocks before a proposal can close",
    type=int,
    default=None,
    required=False,
)
@click.option(
    "-sc",
    "--soft-close",
    help="The number of blocks a proposal must remain unspent before closing",
    type=int,
    default=None,
    required=False,
)
@click.option(
    "-ar",
    "--attendance-required",
    help="The minimum number of votes a proposal must receive to be accepted",
    type=int,
    default=None,
    required=False,
)
@click.option(
    "-pp",
    "--pass-percentage",
    help="The percentage of 'yes' votes in basis points a proposal must receive to be accepted. 100% = 10000",
    type=int,
    default=None,
    required=False,
)
@click.option(
    "-sd",
    "--self-destruct",
    help="The number of blocks required before a proposal can be automatically removed",
    type=int,
    default=None,
    required=False,
)
@click.option(
    "-od",
    "--oracle-delay",
    help="The number of blocks required between oracle spends of the treasury",
    type=int,
    default=None,
    required=False,
)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def dao_create_update_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    proposal_timelock: Optional[int],
    attendance_required: Optional[int],
    pass_percentage: Optional[int],
    self_destruct: Optional[int],
    oracle_delay: Optional[int],
    fee: Optional[int],
) -> None:
    import asyncio

    from .dao_funcs import create_update_proposal

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "proposal_timelock": proposal_timelock,
        "attendance_required": attendance_required,
        "pass_percentage": pass_percentage,
        "self_destruct_length": self_destruct,
        "oracle_spend_delay": oracle_delay,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, create_update_proposal))


@dao_proposal.command("mint", short_help="Create a proposal to mint new DAO CATs", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
@click.option(
    "-a",
    "--amount",
    help="The amount of new cats the proposal will mint",
    type=int,
    required=True,
)
@click.option(
    "-m",
    "--fee",
    help="Set the fees per transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
def dao_create_mint_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    amount: int,
    fee: Optional[int],
) -> None:
    import asyncio

    from .dao_funcs import create_mint_proposal

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "amount": amount,
    }
    asyncio.run(execute_with_wallet(wallet_rpc_port, fingerprint, extra_params, create_mint_proposal))


# ----------------------------------------------------------------------------------------

dao_cmd.add_command(dao_add_cmd)
dao_cmd.add_command(dao_create_cmd)
dao_cmd.add_command(dao_add_funds_cmd)
dao_cmd.add_command(dao_get_balance_cmd)
dao_cmd.add_command(dao_list_proposals_cmd)
dao_cmd.add_command(dao_show_proposal_cmd)
dao_cmd.add_command(dao_vote_cmd)
dao_cmd.add_command(dao_close_proposal_cmd)
dao_cmd.add_command(dao_lockup_coins_cmd)
dao_cmd.add_command(dao_release_coins_cmd)
dao_cmd.add_command(dao_proposal)


# TODO: status: how many of your voting coins are locked away vs. spendable, etc.
