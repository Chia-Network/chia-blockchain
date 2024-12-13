from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

from chia.cmds.cmd_classes import Context, command_helper, option
from chia.cmds.cmds_util import get_wallet_client
from chia.rpc.wallet_rpc_client import WalletRpcClient


@dataclass(frozen=True)
class WalletClientInfo:
    client: WalletRpcClient
    fingerprint: int
    config: dict[str, Any]


@command_helper
class NeedsWalletRPC:
    context: Context = field(default_factory=dict)
    client_info: Optional[WalletClientInfo] = None
    wallet_rpc_port: Optional[int] = option(
        "-wp",
        "--wallet-rpc_port",
        help=(
            "Set the port where the Wallet is hosting the RPC interface."
            "See the rpc_port under wallet in config.yaml."
        ),
        type=int,
        default=None,
    )
    fingerprint: Optional[int] = option(
        "-f",
        "--fingerprint",
        help="Fingerprint of the wallet to use",
        type=int,
        default=None,
    )

    @asynccontextmanager
    async def wallet_rpc(self, **kwargs: Any) -> AsyncIterator[WalletClientInfo]:
        if self.client_info is not None:
            yield self.client_info
        else:
            root_path = kwargs.get("root_path", self.context["root_path"])
            async with get_wallet_client(root_path, self.wallet_rpc_port, self.fingerprint, **kwargs) as (
                wallet_client,
                fp,
                config,
            ):
                yield WalletClientInfo(wallet_client, fp, config)
