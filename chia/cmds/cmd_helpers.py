from __future__ import annotations

from collections.abc import AsyncIterator, Coroutine, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.cmds.cmd_classes import ChiaCliContext, command_helper, option
from chia.cmds.cmds_util import CMDCoinSelectionConfigLoader, CMDTXConfigLoader, TransactionBundle, get_wallet_client
from chia.cmds.param_types import AmountParamType, Bytes32ParamType, CliAmount, TransactionFeeParamType, cli_amount_none
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.tx_config import CoinSelectionConfig, TXConfig
from chia.wallet.wallet_rpc_client import WalletRpcClient


@dataclass(frozen=True)
class WalletClientInfo:
    client: WalletRpcClient
    fingerprint: int
    config: dict[str, Any]


@command_helper
class NeedsWalletRPC:
    context: ChiaCliContext = field(default_factory=ChiaCliContext)
    client_info: Optional[WalletClientInfo] = None
    wallet_rpc_port: Optional[int] = option(
        "-wp",
        "--wallet-rpc_port",
        help=(
            "Set the port where the Wallet is hosting the RPC interface. See the rpc_port under wallet in config.yaml."
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
            root_path = kwargs.get("root_path", self.context.root_path)
            async with get_wallet_client(root_path, self.wallet_rpc_port, self.fingerprint, **kwargs) as (
                wallet_client,
                fp,
                config,
            ):
                yield WalletClientInfo(wallet_client, fp, config)


@command_helper
class TransactionsIn:
    transaction_file_in: str = option(
        "--transaction-file-in",
        type=str,
        help="Transaction file to use as input",
        required=True,
    )

    @cached_property
    def transaction_bundle(self) -> TransactionBundle:
        with open(Path(self.transaction_file_in), "rb") as file:
            return TransactionBundle.from_bytes(file.read())


@command_helper
class TransactionsOut:
    transaction_file_out: Optional[str] = option(
        "--transaction-file-out",
        type=str,
        default=None,
        help="A file to write relevant transactions to",
        required=False,
    )

    def handle_transaction_output(self, output: list[TransactionRecord]) -> None:
        if self.transaction_file_out is None:
            return
        else:
            with open(Path(self.transaction_file_out), "wb") as file:
                file.write(bytes(TransactionBundle(output)))


@command_helper
class NeedsCoinSelectionConfig:
    min_coin_amount: CliAmount = option(
        "-ma",
        "--min-coin-amount",
        "--min-amount",
        help="Ignore coins worth less then this much XCH or CAT units",
        type=AmountParamType(),
        required=False,
        default=cli_amount_none,
    )
    max_coin_amount: CliAmount = option(
        "-l",
        "--max-coin-amount",
        "--max-amount",
        help="Ignore coins worth more then this much XCH or CAT units",
        type=AmountParamType(),
        required=False,
        default=cli_amount_none,
    )
    coins_to_exclude: Sequence[bytes32] = option(
        "--exclude-coin",
        multiple=True,
        type=Bytes32ParamType(),
        help="Exclude this coin from being spent.",
    )
    amounts_to_exclude: Sequence[CliAmount] = option(
        "--exclude-amount",
        multiple=True,
        type=AmountParamType(),
        help="Exclude any coins with this XCH or CAT amount from being included.",
    )

    def load_coin_selection_config(self, mojo_per_unit: int) -> CoinSelectionConfig:
        return CMDCoinSelectionConfigLoader(
            min_coin_amount=self.min_coin_amount,
            max_coin_amount=self.max_coin_amount,
            excluded_coin_amounts=list(_ for _ in self.amounts_to_exclude),
            excluded_coin_ids=list(_ for _ in self.coins_to_exclude),
        ).to_coin_selection_config(mojo_per_unit)


@command_helper
class NeedsTXConfig(NeedsCoinSelectionConfig):
    reuse: Optional[bool] = option(
        "--reuse/--new-address",
        "--reuse-puzhash/--generate-new-puzhash",
        help="Reuse existing address for the change.",
        is_flag=True,
        default=None,
    )

    def load_tx_config(self, mojo_per_unit: int, config: dict[str, Any], fingerprint: int) -> TXConfig:
        return CMDTXConfigLoader(
            min_coin_amount=self.min_coin_amount,
            max_coin_amount=self.max_coin_amount,
            excluded_coin_amounts=list(_ for _ in self.amounts_to_exclude),
            excluded_coin_ids=list(_ for _ in self.coins_to_exclude),
            reuse_puzhash=self.reuse,
        ).to_tx_config(mojo_per_unit, config, fingerprint)


def transaction_endpoint_runner(
    func: Callable[[_T_TransactionEndpoint], Coroutine[Any, Any, list[TransactionRecord]]],
) -> Callable[[_T_TransactionEndpoint], Coroutine[Any, Any, None]]:
    async def wrapped_func(self: _T_TransactionEndpoint) -> None:
        txs = await func(self)
        self.transaction_writer.handle_transaction_output(txs)

    setattr(wrapped_func, _TRANSACTION_ENDPOINT_DECORATOR_APPLIED, True)
    return wrapped_func


_TRANSACTION_ENDPOINT_DECORATOR_APPLIED = (
    f"_{__name__.replace('.', '_')}_{transaction_endpoint_runner.__qualname__}_applied"
)


@dataclass(frozen=True)
class TransactionEndpoint:
    rpc_info: NeedsWalletRPC
    tx_config_loader: NeedsTXConfig
    transaction_writer: TransactionsOut
    fee: uint64 = option(
        "-m",
        "--fee",
        help="Set the fees for the transaction, in XCH",
        type=TransactionFeeParamType(),
        default="0",
        show_default=True,
        required=True,
    )
    push: bool = option(
        "--push/--no-push", help="Push the transaction to the network", type=bool, is_flag=True, default=True
    )
    valid_at: Optional[int] = option(
        "--valid-at",
        help="UNIX timestamp at which the associated transactions become valid",
        type=int,
        required=False,
        default=None,
        hidden=True,
    )
    expires_at: Optional[int] = option(
        "--expires-at",
        help="UNIX timestamp at which the associated transactions expire",
        type=int,
        required=False,
        default=None,
        hidden=True,
    )

    def __post_init__(self) -> None:
        if not hasattr(self.run, _TRANSACTION_ENDPOINT_DECORATOR_APPLIED):
            raise TypeError("TransactionEndpoints must utilize @transaction_endpoint_runner on their `run` method")

    def load_condition_valid_times(self) -> ConditionValidTimes:
        return ConditionValidTimes(
            min_time=uint64.construct_optional(self.valid_at),
            max_time=uint64.construct_optional(self.expires_at),
        )

    @transaction_endpoint_runner
    async def run(self) -> list[TransactionRecord]:
        raise NotImplementedError("Must implement `.run()` on a TransactionEndpoint subclass")  # pragma: no cover


@dataclass(frozen=True)
class TransactionEndpointWithTimelocks(TransactionEndpoint):
    valid_at: Optional[int] = option(
        "--valid-at",
        help="UNIX timestamp at which the associated transactions become valid",
        type=int,
        required=False,
        default=None,
    )
    expires_at: Optional[int] = option(
        "--expires-at",
        help="UNIX timestamp at which the associated transactions expire",
        type=int,
        required=False,
        default=None,
    )


_T_TransactionEndpoint = TypeVar("_T_TransactionEndpoint", bound=TransactionEndpoint)
