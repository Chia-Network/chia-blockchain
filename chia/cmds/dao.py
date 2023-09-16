from __future__ import annotations

import asyncio
from typing import Optional, Sequence

import click

from chia.cmds.cmds_util import tx_config_args
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
    "-a",
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
    from .dao_funcs import add_dao_wallet

    extra_params = {
        "name": name,
        "treasury_id": treasury_id,
        "filter_amount": filter_amount,
    }

    asyncio.run(add_dao_wallet(extra_params, wallet_rpc_port, fingerprint))


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
    "--proposal-timelock",
    help="The minimum number of blocks before a proposal can close",
    type=int,
    default=1000,
    show_default=True,
)
@click.option(
    "--soft-close",
    help="The number of blocks a proposal must remain unspent before closing",
    type=int,
    default=20,
    show_default=True,
)
@click.option(
    "--attendance-required",
    help="The minimum number of votes a proposal must receive to be accepted",
    type=int,
    required=True,
)
@click.option(
    "--pass-percentage",
    help="The percentage of 'yes' votes in basis points a proposal must receive to be accepted. 100% = 10000",
    type=int,
    default=5000,
    show_default=True,
)
@click.option(
    "--self-destruct",
    help="The number of blocks required before a proposal can be automatically removed",
    type=int,
    default=10000,
    show_default=True,
)
@click.option(
    "--oracle-delay",
    help="The number of blocks required between oracle spends of the treasury",
    type=int,
    default=50,
    show_default=True,
)
@click.option(
    "--proposal-minimum",
    help="The minimum amount (in xch) that a proposal must use to be created",
    type=str,
    default="0.000000000001",
    show_default=True,
)
@click.option(
    "--filter-amount",
    help="The minimum number of votes a proposal needs before the wallet will recognise it",
    type=int,
    default=1,
    show_default=True,
)
@click.option(
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
@click.option(
    "--fee-for-cat",
    help="Set the fees for the CAT creation transaction, in XCH.",
    type=str,
    default="0",
    show_default=True,
    callback=validate_fee,
)
@tx_config_args
def dao_create_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    proposal_timelock: int,
    soft_close: int,
    attendance_required: int,
    pass_percentage: int,
    self_destruct: int,
    oracle_delay: int,
    proposal_minimum: str,
    filter_amount: int,
    cat_amount: int,
    name: Optional[str],
    fee: str,
    fee_for_cat: str,
    min_coin_amount: Optional[str],
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    amounts_to_exclude: Sequence[str],
    reuse: Optional[bool],
) -> None:
    from .dao_funcs import create_dao_wallet

    print("Creating new DAO")

    extra_params = {
        "fee": fee,
        "fee_for_cat": fee_for_cat,
        "name": name,
        "proposal_timelock": proposal_timelock,
        "soft_close_length": soft_close,
        "attendance_required": attendance_required,
        "pass_percentage": pass_percentage,
        "self_destruct_length": self_destruct,
        "oracle_spend_delay": oracle_delay,
        "proposal_minimum_amount": proposal_minimum,
        "filter_amount": filter_amount,
        "amount_of_cats": cat_amount,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "coins_to_exclude": coins_to_exclude,
        "amounts_to_exclude": amounts_to_exclude,
        "reuse_puzhash": reuse,
    }
    asyncio.run(create_dao_wallet(extra_params, wallet_rpc_port, fingerprint))


# ----------------------------------------------------------------------------------------
# TREASURY INFO


@dao_cmd.command("get_id", short_help="Get the Treasury ID of a DAO", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="DAO Wallet ID", type=int, required=True)
def dao_get_id_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
) -> None:
    from .dao_funcs import get_treasury_id

    extra_params = {
        "wallet_id": wallet_id,
    }
    asyncio.run(get_treasury_id(extra_params, wallet_rpc_port, fingerprint))


@dao_cmd.command("add_funds", short_help="Send funds to a DAO treasury", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="DAO Wallet ID which will receive the funds", type=int, required=True)
@click.option(
    "-w",
    "--funding-wallet-id",
    help="ID of the wallet to send funds from",
    type=int,
    required=True,
)
@click.option(
    "-a",
    "--amount",
    help="The amount of funds to send",
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
@tx_config_args
def dao_add_funds_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    funding_wallet_id: int,
    amount: str,
    fee: str,
    min_coin_amount: Optional[str],
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    amounts_to_exclude: Sequence[str],
    reuse: Optional[bool],
) -> None:
    from .dao_funcs import add_funds_to_treasury

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "funding_wallet_id": funding_wallet_id,
        "amount": amount,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "coins_to_exclude": coins_to_exclude,
        "amounts_to_exclude": amounts_to_exclude,
        "reuse_puzhash": reuse,
    }
    asyncio.run(add_funds_to_treasury(extra_params, wallet_rpc_port, fingerprint))


@dao_cmd.command("balance", short_help="Get the asset balances for a DAO treasury", no_args_is_help=True)
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
    from .dao_funcs import get_treasury_balance

    extra_params = {
        "wallet_id": wallet_id,
    }
    asyncio.run(get_treasury_balance(extra_params, wallet_rpc_port, fingerprint))


@dao_cmd.command("rules", short_help="Get the current rules governing the DAO", no_args_is_help=True)
@click.option(
    "-wp",
    "--wallet-rpc-port",
    help="Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml",
    type=int,
    default=None,
)
@click.option("-f", "--fingerprint", help="Set the fingerprint to specify which key to use", type=int)
@click.option("-i", "--wallet-id", help="Id of the wallet to use", type=int, required=True)
def dao_rules_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
) -> None:
    from .dao_funcs import get_rules

    extra_params = {
        "wallet_id": wallet_id,
    }
    asyncio.run(get_rules(extra_params, wallet_rpc_port, fingerprint))


# ----------------------------------------------------------------------------------------
# LIST/SHOW PROPOSALS


@dao_cmd.command("list_proposals", short_help="List proposals for the DAO", no_args_is_help=True)
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
    from .dao_funcs import list_proposals

    if not include_closed:
        include_closed = False

    extra_params = {
        "wallet_id": wallet_id,
        "include_closed": include_closed,
    }
    asyncio.run(list_proposals(extra_params, wallet_rpc_port, fingerprint))


@dao_cmd.command("show_proposal", short_help="Show the details of a specific proposal", no_args_is_help=True)
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
    from .dao_funcs import show_proposal

    extra_params = {
        "wallet_id": wallet_id,
        "proposal_id": proposal_id,
    }
    asyncio.run(show_proposal(extra_params, wallet_rpc_port, fingerprint))


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
@tx_config_args
def dao_vote_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    proposal_id: str,
    vote_amount: int,
    vote_no: Optional[bool],
    fee: str,
    min_coin_amount: Optional[str],
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    amounts_to_exclude: Sequence[str],
    reuse: Optional[bool],
) -> None:
    from .dao_funcs import vote_on_proposal

    is_yes_vote = False if vote_no else True

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "proposal_id": proposal_id,
        "vote_amount": vote_amount,
        "is_yes_vote": is_yes_vote,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "coins_to_exclude": coins_to_exclude,
        "amounts_to_exclude": amounts_to_exclude,
        "reuse_puzhash": reuse,
    }
    asyncio.run(vote_on_proposal(extra_params, wallet_rpc_port, fingerprint))


# ----------------------------------------------------------------------------------------
# CLOSE PROPOSALS


@dao_cmd.command("close_proposal", short_help="Close a DAO proposal", no_args_is_help=True)
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
    "-d",
    "--self-destruct",
    help="If a proposal is broken, use self destruct to force it to close",
    is_flag=True,
    default=False,
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
@tx_config_args
def dao_close_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    proposal_id: str,
    self_destruct: bool,
    fee: str,
    min_coin_amount: Optional[str],
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    amounts_to_exclude: Sequence[str],
    reuse: Optional[bool],
) -> None:
    from .dao_funcs import close_proposal

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "proposal_id": proposal_id,
        "self_destruct": self_destruct,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "coins_to_exclude": coins_to_exclude,
        "amounts_to_exclude": amounts_to_exclude,
        "reuse_puzhash": reuse,
    }
    asyncio.run(close_proposal(extra_params, wallet_rpc_port, fingerprint))


# ----------------------------------------------------------------------------------------
# LOCKUP COINS


@dao_cmd.command("lockup_coins", short_help="Lock DAO CATs for voting", no_args_is_help=True)
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
    help="The amount of CATs (not mojos) to lock in voting mode",
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
@tx_config_args
def dao_lockup_coins_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    amount: str,
    fee: str,
    min_coin_amount: Optional[str],
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    amounts_to_exclude: Sequence[str],
    reuse: Optional[bool],
) -> None:
    from .dao_funcs import lockup_coins

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "amount": amount,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "coins_to_exclude": coins_to_exclude,
        "amounts_to_exclude": amounts_to_exclude,
        "reuse_puzhash": reuse,
    }
    asyncio.run(lockup_coins(extra_params, wallet_rpc_port, fingerprint))


@dao_cmd.command("release_coins", short_help="Release closed proposals from DAO CATs", no_args_is_help=True)
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
@tx_config_args
def dao_release_coins_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    fee: str,
    min_coin_amount: Optional[str],
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    amounts_to_exclude: Sequence[str],
    reuse: Optional[bool],
) -> None:
    from .dao_funcs import release_coins

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "coins_to_exclude": coins_to_exclude,
        "amounts_to_exclude": amounts_to_exclude,
        "reuse_puzhash": reuse,
    }
    asyncio.run(release_coins(extra_params, wallet_rpc_port, fingerprint))


@dao_cmd.command("exit_lockup", short_help="Release DAO CATs from voting mode", no_args_is_help=True)
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
@tx_config_args
def dao_exit_lockup_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    fee: str,
    min_coin_amount: Optional[str],
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    amounts_to_exclude: Sequence[str],
    reuse: Optional[bool],
) -> None:
    from .dao_funcs import exit_lockup

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "coins_to_exclude": coins_to_exclude,
        "amounts_to_exclude": amounts_to_exclude,
        "reuse_puzhash": reuse,
    }
    asyncio.run(exit_lockup(extra_params, wallet_rpc_port, fingerprint))


# ----------------------------------------------------------------------------------------
# CREATE PROPOSALS


@dao_cmd.group("create_proposal", short_help="Create and add a proposal to a DAO", no_args_is_help=True)
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
    help="The amount of funds the proposal will send (in mojos)",
    type=float,
    required=False,
    default=None,
)
@click.option(
    "-v",
    "--vote-amount",
    help="The number of votes to add",
    type=int,
    required=False,
    default=None,
)
@click.option(
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
@tx_config_args
def dao_create_spend_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    vote_amount: Optional[int],
    to_address: Optional[str],
    amount: Optional[str],
    asset_id: Optional[str],
    from_json: Optional[str],
    fee: str,
    min_coin_amount: Optional[str],
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    amounts_to_exclude: Sequence[str],
    reuse: Optional[bool],
) -> None:
    from .dao_funcs import create_spend_proposal

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "vote_amount": vote_amount,
        "to_address": to_address,
        "amount": amount,
        "asset_id": asset_id,
        "from_json": from_json,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "coins_to_exclude": coins_to_exclude,
        "amounts_to_exclude": amounts_to_exclude,
        "reuse_puzhash": reuse,
    }
    asyncio.run(create_spend_proposal(extra_params, wallet_rpc_port, fingerprint))


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
    "-v",
    "--vote-amount",
    help="The number of votes to add",
    type=int,
    required=False,
    default=None,
)
@click.option(
    "--proposal-timelock",
    help="The new minimum number of blocks before a proposal can close",
    type=int,
    default=None,
    required=False,
)
@click.option(
    "--soft-close",
    help="The number of blocks a proposal must remain unspent before closing",
    type=int,
    default=None,
    required=False,
)
@click.option(
    "--attendance-required",
    help="The minimum number of votes a proposal must receive to be accepted",
    type=int,
    default=None,
    required=False,
)
@click.option(
    "--pass-percentage",
    help="The percentage of 'yes' votes in basis points a proposal must receive to be accepted. 100% = 10000",
    type=int,
    default=None,
    required=False,
)
@click.option(
    "--self-destruct",
    help="The number of blocks required before a proposal can be automatically removed",
    type=int,
    default=None,
    required=False,
)
@click.option(
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
@tx_config_args
def dao_create_update_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    vote_amount: Optional[int],
    proposal_timelock: Optional[int],
    soft_close: Optional[int],
    attendance_required: Optional[int],
    pass_percentage: Optional[int],
    self_destruct: Optional[int],
    oracle_delay: Optional[int],
    fee: str,
    min_coin_amount: Optional[str],
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    amounts_to_exclude: Sequence[str],
    reuse: Optional[bool],
) -> None:
    from .dao_funcs import create_update_proposal

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "vote_amount": vote_amount,
        "proposal_timelock": proposal_timelock,
        "soft_close_length": soft_close,
        "attendance_required": attendance_required,
        "pass_percentage": pass_percentage,
        "self_destruct_length": self_destruct,
        "oracle_spend_delay": oracle_delay,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "coins_to_exclude": coins_to_exclude,
        "amounts_to_exclude": amounts_to_exclude,
        "reuse_puzhash": reuse,
    }
    asyncio.run(create_update_proposal(extra_params, wallet_rpc_port, fingerprint))


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
    help="The amount of new cats the proposal will mint (in mojos)",
    type=int,
    required=True,
)
@click.option(
    "-t",
    "--to-address",
    help="The address new cats will be minted to",
    type=str,
    required=True,
    default=None,
)
@click.option(
    "-v",
    "--vote-amount",
    help="The number of votes to add",
    type=int,
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
@tx_config_args
def dao_create_mint_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    amount: int,
    to_address: int,
    vote_amount: Optional[int],
    fee: str,
    min_coin_amount: Optional[str],
    max_coin_amount: Optional[str],
    coins_to_exclude: Sequence[str],
    amounts_to_exclude: Sequence[str],
    reuse: Optional[bool],
) -> None:
    from .dao_funcs import create_mint_proposal

    extra_params = {
        "wallet_id": wallet_id,
        "fee": fee,
        "amount": amount,
        "cat_target_address": to_address,
        "vote_amount": vote_amount,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "coins_to_exclude": coins_to_exclude,
        "amounts_to_exclude": amounts_to_exclude,
        "reuse_puzhash": reuse,
    }
    asyncio.run(create_mint_proposal(extra_params, wallet_rpc_port, fingerprint))


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
dao_cmd.add_command(dao_exit_lockup_cmd)
dao_cmd.add_command(dao_release_coins_cmd)
dao_cmd.add_command(dao_proposal)
