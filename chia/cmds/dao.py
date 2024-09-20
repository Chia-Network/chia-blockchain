from __future__ import annotations

import asyncio
from typing import List, Optional, Sequence

import click

from chia.cmds import options
from chia.cmds.cmds_util import CMDTXConfigLoader, tx_config_args, tx_out_cmd
from chia.cmds.param_types import AmountParamType, Bytes32ParamType, CliAmount, TransactionFeeParamType, Uint64ParamType
from chia.cmds.units import units
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord


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
    type=Bytes32ParamType(),
    required=True,
)
@click.option(
    "-a",
    "--filter-amount",
    help="The minimum number of votes a proposal needs before the wallet will recognise it",
    type=Uint64ParamType(),
    default=uint64(1),
    show_default=True,
)
def dao_add_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    treasury_id: bytes32,
    filter_amount: uint64,
    name: Optional[str],
) -> None:
    from .dao_funcs import add_dao_wallet

    asyncio.run(add_dao_wallet(wallet_rpc_port, fingerprint, name, treasury_id, filter_amount))


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
    type=Uint64ParamType(),
    default="1000",
    show_default=True,
)
@click.option(
    "--soft-close",
    help="The number of blocks a proposal must remain unspent before closing",
    type=Uint64ParamType(),
    default="20",
    show_default=True,
)
@click.option(
    "--attendance-required",
    help="The minimum number of votes a proposal must receive to be accepted",
    type=Uint64ParamType(),
    required=True,
)
@click.option(
    "--pass-percentage",
    help="The percentage of 'yes' votes in basis points a proposal must receive to be accepted. 100% = 10000",
    type=Uint64ParamType(),
    default="5000",
    show_default=True,
)
@click.option(
    "--self-destruct",
    help="The number of blocks required before a proposal can be automatically removed",
    type=Uint64ParamType(),
    default="10000",
    show_default=True,
)
@click.option(
    "--oracle-delay",
    help="The number of blocks required between oracle spends of the treasury",
    type=Uint64ParamType(),
    default="50",
    show_default=True,
)
@click.option(
    "--proposal-minimum",
    help="The minimum amount (in xch) that a proposal must use to be created",
    type=AmountParamType(),
    default="1",
    show_default=True,
)
@click.option(
    "--filter-amount",
    help="The minimum number of votes a proposal needs before the wallet will recognise it",
    type=Uint64ParamType(),
    default="1",
    show_default=True,
)
@click.option(
    "--cat-amount",
    help="The number of DAO CATs (in mojos) to create when initializing the DAO",
    type=AmountParamType(),
    required=True,
)
@options.create_fee()
@click.option(
    "--fee-for-cat",
    help="Set the fees for the CAT creation transaction, in XCH.",
    type=TransactionFeeParamType(),
    default="0",
    show_default=True,
)
@tx_config_args
@tx_out_cmd()
def dao_create_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    proposal_timelock: uint64,
    soft_close: uint64,
    attendance_required: uint64,
    pass_percentage: uint64,
    self_destruct: uint64,
    oracle_delay: uint64,
    proposal_minimum: CliAmount,
    filter_amount: uint64,
    cat_amount: CliAmount,
    name: Optional[str],
    fee: uint64,
    fee_for_cat: uint64,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    amounts_to_exclude: Sequence[CliAmount],
    reuse: Optional[bool],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .dao_funcs import create_dao_wallet

    if self_destruct == proposal_timelock:
        raise ValueError("Self Destruct and Proposal Timelock cannot be the same value")

    print("Creating new DAO")

    return asyncio.run(
        create_dao_wallet(
            wallet_rpc_port,
            fingerprint,
            fee,
            fee_for_cat,
            name,
            proposal_timelock,
            soft_close,
            attendance_required,
            pass_percentage,
            self_destruct,
            oracle_delay,
            proposal_minimum.convert_amount(units["chia"]),
            filter_amount,
            cat_amount,
            CMDTXConfigLoader(
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_ids=list(coins_to_exclude),
                excluded_coin_amounts=list(amounts_to_exclude),
                reuse_puzhash=reuse,
            ),
            push,
            condition_valid_times=condition_valid_times,
        )
    )


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

    asyncio.run(get_treasury_id(wallet_rpc_port, fingerprint, wallet_id))


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
    help="The amount of funds to send, in XCH or CATs",
    type=AmountParamType(),
    required=True,
)
@options.create_fee()
@tx_config_args
@tx_out_cmd()
def dao_add_funds_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    funding_wallet_id: int,
    amount: CliAmount,
    fee: uint64,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    amounts_to_exclude: Sequence[CliAmount],
    reuse: Optional[bool],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .dao_funcs import add_funds_to_treasury

    return asyncio.run(
        add_funds_to_treasury(
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            funding_wallet_id,
            amount,
            fee,
            CMDTXConfigLoader(
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_ids=list(coins_to_exclude),
                excluded_coin_amounts=list(amounts_to_exclude),
                reuse_puzhash=reuse,
            ),
            push,
            condition_valid_times=condition_valid_times,
        )
    )


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

    asyncio.run(get_treasury_balance(wallet_rpc_port, fingerprint, wallet_id))


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

    asyncio.run(get_rules(wallet_rpc_port, fingerprint, wallet_id))


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

    asyncio.run(list_proposals(wallet_rpc_port, fingerprint, wallet_id, include_closed))


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

    asyncio.run(show_proposal(wallet_rpc_port, fingerprint, wallet_id, proposal_id))


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
    type=Uint64ParamType(),
    required=True,
)
@click.option(
    "-n",
    "--vote-no",
    help="Use this option to vote against a proposal. If not present then the vote is for the proposal",
    is_flag=True,
)
@options.create_fee()
@tx_config_args
@tx_out_cmd()
def dao_vote_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    proposal_id: str,
    vote_amount: uint64,
    vote_no: Optional[bool],
    fee: uint64,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    amounts_to_exclude: Sequence[CliAmount],
    reuse: Optional[bool],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .dao_funcs import vote_on_proposal

    is_yes_vote = False if vote_no else True

    return asyncio.run(
        vote_on_proposal(
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            proposal_id,
            vote_amount,
            is_yes_vote,
            fee,
            CMDTXConfigLoader(
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_ids=list(coins_to_exclude),
                excluded_coin_amounts=list(amounts_to_exclude),
                reuse_puzhash=reuse,
            ),
            push,
            condition_valid_times=condition_valid_times,
        )
    )


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
@options.create_fee()
@tx_config_args
@tx_out_cmd()
def dao_close_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    proposal_id: str,
    self_destruct: bool,
    fee: uint64,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    amounts_to_exclude: Sequence[CliAmount],
    reuse: Optional[bool],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .dao_funcs import close_proposal

    return asyncio.run(
        close_proposal(
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            fee,
            proposal_id,
            self_destruct,
            CMDTXConfigLoader(
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_ids=list(coins_to_exclude),
                excluded_coin_amounts=list(amounts_to_exclude),
                reuse_puzhash=reuse,
            ),
            push,
            condition_valid_times=condition_valid_times,
        )
    )


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
    type=AmountParamType(),
    required=True,
)
@options.create_fee()
@tx_config_args
@tx_out_cmd()
def dao_lockup_coins_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    amount: CliAmount,
    fee: uint64,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    amounts_to_exclude: Sequence[CliAmount],
    reuse: Optional[bool],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .dao_funcs import lockup_coins

    return asyncio.run(
        lockup_coins(
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            amount,
            fee,
            CMDTXConfigLoader(
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_ids=list(coins_to_exclude),
                excluded_coin_amounts=list(amounts_to_exclude),
                reuse_puzhash=reuse,
            ),
            push,
            condition_valid_times=condition_valid_times,
        )
    )


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
@options.create_fee()
@tx_config_args
@tx_out_cmd()
def dao_release_coins_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    fee: uint64,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    amounts_to_exclude: Sequence[CliAmount],
    reuse: Optional[bool],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .dao_funcs import release_coins

    return asyncio.run(
        release_coins(
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            fee,
            CMDTXConfigLoader(
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_ids=list(coins_to_exclude),
                excluded_coin_amounts=list(amounts_to_exclude),
                reuse_puzhash=reuse,
            ),
            push,
            condition_valid_times=condition_valid_times,
        )
    )


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
@options.create_fee()
@tx_config_args
@tx_out_cmd()
def dao_exit_lockup_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    fee: uint64,
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    amounts_to_exclude: Sequence[CliAmount],
    reuse: Optional[bool],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .dao_funcs import exit_lockup

    return asyncio.run(
        exit_lockup(
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            fee,
            CMDTXConfigLoader(
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_ids=list(coins_to_exclude),
                excluded_coin_amounts=list(amounts_to_exclude),
                reuse_puzhash=reuse,
            ),
            push,
            condition_valid_times=condition_valid_times,
        )
    )


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
    type=str,
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
@options.create_fee()
@tx_config_args
@tx_out_cmd()
def dao_create_spend_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    fee: uint64,
    vote_amount: Optional[int],
    to_address: Optional[str],
    amount: Optional[str],
    asset_id: Optional[str],
    from_json: Optional[str],
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    amounts_to_exclude: Sequence[CliAmount],
    reuse: Optional[bool],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .dao_funcs import create_spend_proposal

    return asyncio.run(
        create_spend_proposal(
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            fee,
            vote_amount,
            to_address,
            amount,
            asset_id,
            from_json,
            CMDTXConfigLoader(
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_ids=list(coins_to_exclude),
                excluded_coin_amounts=list(amounts_to_exclude),
                reuse_puzhash=reuse,
            ),
            push,
            condition_valid_times=condition_valid_times,
        )
    )


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
    type=Uint64ParamType(),
    required=False,
    default=None,
)
@click.option(
    "--proposal-timelock",
    help="The new minimum number of blocks before a proposal can close",
    type=Uint64ParamType(),
    default=None,
    required=False,
)
@click.option(
    "--soft-close",
    help="The number of blocks a proposal must remain unspent before closing",
    type=Uint64ParamType(),
    default=None,
    required=False,
)
@click.option(
    "--attendance-required",
    help="The minimum number of votes a proposal must receive to be accepted",
    type=Uint64ParamType(),
    default=None,
    required=False,
)
@click.option(
    "--pass-percentage",
    help="The percentage of 'yes' votes in basis points a proposal must receive to be accepted. 100% = 10000",
    type=Uint64ParamType(),
    default=None,
    required=False,
)
@click.option(
    "--self-destruct",
    help="The number of blocks required before a proposal can be automatically removed",
    type=Uint64ParamType(),
    default=None,
    required=False,
)
@click.option(
    "--oracle-delay",
    help="The number of blocks required between oracle spends of the treasury",
    type=Uint64ParamType(),
    default=None,
    required=False,
)
@options.create_fee()
@tx_config_args
@tx_out_cmd()
def dao_create_update_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    fee: uint64,
    vote_amount: Optional[uint64],
    proposal_timelock: Optional[uint64],
    soft_close: Optional[uint64],
    attendance_required: Optional[uint64],
    pass_percentage: Optional[uint64],
    self_destruct: Optional[uint64],
    oracle_delay: Optional[uint64],
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    amounts_to_exclude: Sequence[CliAmount],
    reuse: Optional[bool],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .dao_funcs import create_update_proposal

    return asyncio.run(
        create_update_proposal(
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            fee,
            vote_amount,
            proposal_timelock,
            soft_close,
            attendance_required,
            pass_percentage,
            self_destruct,
            oracle_delay,
            CMDTXConfigLoader(
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_ids=list(coins_to_exclude),
                excluded_coin_amounts=list(amounts_to_exclude),
                reuse_puzhash=reuse,
            ),
            push,
            condition_valid_times=condition_valid_times,
        )
    )


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
    type=Uint64ParamType(),
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
@options.create_fee()
@tx_config_args
@tx_out_cmd()
def dao_create_mint_proposal_cmd(
    wallet_rpc_port: Optional[int],
    fingerprint: int,
    wallet_id: int,
    fee: uint64,
    amount: uint64,
    to_address: str,
    vote_amount: Optional[int],
    min_coin_amount: CliAmount,
    max_coin_amount: CliAmount,
    coins_to_exclude: Sequence[bytes32],
    amounts_to_exclude: Sequence[CliAmount],
    reuse: Optional[bool],
    push: bool,
    condition_valid_times: ConditionValidTimes,
) -> List[TransactionRecord]:
    from .dao_funcs import create_mint_proposal

    return asyncio.run(
        create_mint_proposal(
            wallet_rpc_port,
            fingerprint,
            wallet_id,
            fee,
            amount,
            to_address,
            vote_amount,
            CMDTXConfigLoader(
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_ids=list(coins_to_exclude),
                excluded_coin_amounts=list(amounts_to_exclude),
                reuse_puzhash=reuse,
            ),
            push,
            condition_valid_times=condition_valid_times,
        )
    )


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
