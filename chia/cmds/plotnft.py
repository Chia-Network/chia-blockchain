from __future__ import annotations

from dataclasses import field
from typing import Any, Optional

import click

from chia.cmds.cmd_classes import NeedsWalletRPC, chia_command, option
from chia.cmds.param_types import (
    AddressParamType,
    Bytes32ParamType,
    CliAddress,
    TransactionFeeParamType,
)
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.errors import CliRpcConnectionError
from chia.util.ints import uint64


@click.group("plotnft", help="Manage your plot NFTs")
@click.pass_context
def plotnft_cmd(ctx: click.Context) -> None:
    pass


@chia_command(
    plotnft_cmd,
    "show",
    "Show plotnft information",
)
class ShowPlotNFTCMD:
    context: dict[str, Any]
    rpc_info: NeedsWalletRPC  # provides wallet-rpc-port and fingerprint options
    id: Optional[int] = option(
        "-i", "--id", help="ID of the wallet to use", default=None, show_default=True, required=False
    )

    async def run(self) -> None:
        from .plotnft_funcs import show

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await show(
                wallet_info=wallet_info,
                root_path=self.context.get("root_path"),
                wallet_id_passed_in=self.id,
            )


@chia_command(
    plotnft_cmd,
    "get_login_link",
    "Create a login link for a pool. The farmer must be running. To get the launcher id, use plotnft show.",
)
class GetLoginLinkCMD:
    context: dict[str, Any] = field(default_factory=dict)
    launcher_id: bytes32 = option(
        "-l", "--launcher_id", help="Launcher ID of the plotnft", type=Bytes32ParamType(), required=True
    )

    async def run(self) -> None:
        from .plotnft_funcs import get_login_link

        await get_login_link(self.launcher_id, root_path=self.context.get("root_path"))


# Functions with this mark in this file are not being ported to @tx_out_cmd due to lack of observer key support
# They will therefore not work with observer-only functionality
# NOTE: tx_endpoint  (This creates wallet transactions and should be parametrized by relevant options)
@chia_command(
    plotnft_cmd,
    "create",
    "Create a plot NFT",
)
class CreatePlotNFTCMD:
    rpc_info: NeedsWalletRPC  # provides wallet-rpc-port and fingerprint options
    pool_url: Optional[str] = option("-u", "--pool-url", help="HTTPS host:port of the pool to join", required=False)
    state: str = option(
        "-s",
        "--state",
        help="Initial state of Plot NFT: local or pool",
        required=True,
        type=click.Choice(["local", "pool"], case_sensitive=False),
    )
    fee: uint64 = option(
        "-m",
        "--fee",
        help="Set the fees per transaction, in XCH. Fee is used TWICE: once to create the singleton, once for init.",
        type=TransactionFeeParamType(),
        default="0",
        show_default=True,
        required=True,
    )
    dont_prompt: bool = option("-y", "--yes", "dont_prompt", help="No prompts", is_flag=True)

    async def run(self) -> None:
        from .plotnft_funcs import create

        if self.pool_url is not None and self.state == "local":
            raise CliRpcConnectionError(f"A pool url [{self.pool_url}] is not allowed with 'local' state")

        if self.pool_url in {None, ""} and self.state == "pool":
            raise CliRpcConnectionError("A pool url argument (-u/--pool-url) is required with 'pool' state")

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await create(
                wallet_info=wallet_info,
                pool_url=self.pool_url,
                state="FARMING_TO_POOL" if self.state == "pool" else "SELF_POOLING",
                fee=self.fee,
                prompt=not self.dont_prompt,
            )


# NOTE: tx_endpoint
@chia_command(
    plotnft_cmd,
    "join",
    "Join a plot NFT to a Pool",
)
class JoinPlotNFTCMD:
    rpc_info: NeedsWalletRPC  # provides wallet-rpc-port and fingerprint options
    pool_url: str = option("-u", "--pool-url", help="HTTPS host:port of the pool to join", required=True)
    fee: uint64 = option(
        "-m",
        "--fee",
        help="Set the fees per transaction, in XCH. Fee is used TWICE: once to create the singleton, once for init.",
        type=TransactionFeeParamType(),
        default="0",
        show_default=True,
        required=True,
    )
    dont_prompt: bool = option("-y", "--yes", "dont_prompt", help="No prompts", is_flag=True)
    id: Optional[int] = option(
        "-i", "--id", help="ID of the wallet to use", default=None, show_default=True, required=False
    )

    async def run(self) -> None:
        from .plotnft_funcs import join_pool

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await join_pool(
                wallet_info=wallet_info,
                pool_url=self.pool_url,
                fee=self.fee,
                wallet_id=self.id,
                prompt=not self.dont_prompt,
            )


# NOTE: tx_endpoint
@chia_command(
    plotnft_cmd,
    "leave",
    "Leave a pool and return to self-farming",
)
class LeavePlotNFTCMD:
    rpc_info: NeedsWalletRPC  # provides wallet-rpc-port and fingerprint options
    dont_prompt: bool = option("-y", "--yes", "dont_prompt", help="No prompts", is_flag=True)
    fee: uint64 = option(
        "-m",
        "--fee",
        help="Set the fees per transaction, in XCH. Fee is used TWICE: once to create the singleton, once for init.",
        type=TransactionFeeParamType(),
        default="0",
        show_default=True,
        required=True,
    )
    id: Optional[int] = option(
        "-i", "--id", help="ID of the wallet to use", default=None, show_default=True, required=False
    )

    async def run(self) -> None:
        from .plotnft_funcs import self_pool

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await self_pool(
                wallet_info=wallet_info,
                fee=self.fee,
                wallet_id=self.id,
                prompt=not self.dont_prompt,
            )


@chia_command(
    plotnft_cmd,
    "inspect",
    "Get Detailed plotnft information as JSON",
)
class InspectPlotNFTCMD:
    rpc_info: NeedsWalletRPC  # provides wallet-rpc-port and fingerprint options
    id: Optional[int] = option(
        "-i", "--id", help="ID of the wallet to use", default=None, show_default=True, required=False
    )

    async def run(self) -> None:
        from .plotnft_funcs import inspect_cmd

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await inspect_cmd(wallet_info=wallet_info, wallet_id=self.id)


# NOTE: tx_endpoint
@chia_command(
    plotnft_cmd,
    "claim",
    "Claim rewards from a plot NFT",
)
class ClaimPlotNFTCMD:
    rpc_info: NeedsWalletRPC  # provides wallet-rpc-port and fingerprint options
    id: Optional[int] = option(
        "-i", "--id", help="ID of the wallet to use", default=None, show_default=True, required=False
    )
    fee: uint64 = option(
        "-m",
        "--fee",
        help="Set the fees per transaction, in XCH. Fee is used TWICE: once to create the singleton, once for init.",
        type=TransactionFeeParamType(),
        default="0",
        show_default=True,
        required=True,
    )

    async def run(self) -> None:
        from .plotnft_funcs import claim_cmd

        async with self.rpc_info.wallet_rpc() as wallet_info:
            await claim_cmd(
                wallet_info=wallet_info,
                fee=self.fee,
                wallet_id=self.id,
            )


@chia_command(
    plotnft_cmd,
    "change_payout_instructions",
    "Change the payout instructions for a pool. To get the launcher id, use plotnft show",
)
class ChangePayoutInstructionsPlotNFTCMD:
    context: dict[str, Any] = field(default_factory=dict)
    launcher_id: bytes32 = option(
        "-l", "--launcher_id", help="Launcher ID of the plotnft", type=Bytes32ParamType(), required=True
    )
    address: CliAddress = option(
        "-a", "--address", help="New address for payout instructions", type=AddressParamType(), required=True
    )

    async def run(self) -> None:
        from .plotnft_funcs import change_payout_instructions

        await change_payout_instructions(self.launcher_id, self.address, root_path=self.context.get("root_path"))
