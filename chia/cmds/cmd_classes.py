from __future__ import annotations

import asyncio
import inspect
import sys
from contextlib import asynccontextmanager
from dataclasses import MISSING, Field, dataclass, field, fields
from typing import Any, AsyncIterator, Callable, Dict, Iterable, Optional, Protocol, Type, Union

import click
from typing_extensions import dataclass_transform

from chia.cmds.cmds_util import get_wallet_client
from chia.rpc.wallet_rpc_client import WalletRpcClient

SyncCmd = Callable[..., None]


class SyncChiaCommand(Protocol):
    def run(self) -> None:
        ...


class AsyncChiaCommand(Protocol):
    async def run(self) -> None:
        ...


ChiaCommand = Union[SyncChiaCommand, AsyncChiaCommand]


def option(*param_decls: str, **kwargs: Any) -> Any:
    if sys.version_info < (3, 10):  # versions < 3.10 don't know about kw_only and they complain about lacks of defaults
        # Can't get coverage on this because we only test on one version
        default_default = None  # pragma: no cover
    else:
        default_default = MISSING

    return field(  # pylint: disable=invalid-field-call
        metadata=dict(
            is_command_option=True,
            param_decls=tuple(param_decls),
            **kwargs,
        ),
        default=kwargs["default"] if "default" in kwargs else default_default,
    )


def _apply_options(cmd: SyncCmd, _fields: Iterable[Field[Any]]) -> SyncCmd:
    wrapped_cmd = cmd
    for _field in _fields:
        if "is_command_option" not in _field.metadata or not _field.metadata["is_command_option"]:
            continue
        wrapped_cmd = click.option(
            *_field.metadata["param_decls"],
            **{k: v for k, v in _field.metadata.items() if k not in ("param_decls", "is_command_option")},
        )(wrapped_cmd)

    return wrapped_cmd


@dataclass_transform()
def chia_command(cmd: click.Group, name: str, help: str) -> Callable[[Type[ChiaCommand]], Type[ChiaCommand]]:
    def _chia_command(cls: Type[ChiaCommand]) -> Type[ChiaCommand]:
        # The type ignores here are largely due to the fact that the class information is not preserved after being
        # passed through the dataclass wrapper.  Not sure what to do about this right now.
        if sys.version_info < (3, 10):  # pragma: no cover
            # stuff below 3.10 doesn't know about kw_only
            wrapped_cls: Type[ChiaCommand] = dataclass(  # type: ignore[assignment]
                frozen=True,
            )(cls)
        else:
            wrapped_cls: Type[ChiaCommand] = dataclass(  # type: ignore[assignment]
                frozen=True,
                kw_only=True,
            )(cls)
        cls_fields = fields(wrapped_cls)  # type: ignore[arg-type]
        if inspect.iscoroutinefunction(cls.run):

            async def async_base_cmd(*args: Any, **kwargs: Any) -> None:
                await wrapped_cls(*args, **kwargs).run()  # type: ignore[misc]

            def base_cmd(*args: Any, **kwargs: Any) -> None:
                coro = async_base_cmd(*args, **kwargs)
                assert coro is not None
                asyncio.run(coro)

        else:

            def base_cmd(*args: Any, **kwargs: Any) -> None:
                wrapped_cls(**kwargs).run()

        marshalled_cmd = base_cmd
        if issubclass(wrapped_cls, NeedsContext):

            def strip_click_context(func: SyncCmd) -> SyncCmd:
                def _inner(ctx: click.Context, **kwargs: Any) -> None:
                    context: Dict[str, Any] = ctx.obj if ctx.obj is not None else {}
                    func(context=context, **kwargs)

                return _inner

            marshalled_cmd = click.pass_context(strip_click_context(marshalled_cmd))
        marshalled_cmd = _apply_options(marshalled_cmd, cls_fields)
        cmd.command(name, help=help)(marshalled_cmd)
        return wrapped_cls

    return _chia_command


@dataclass_transform()
def command_helper(cls: Type[Any]) -> Type[Any]:
    if sys.version_info < (3, 10):  # stuff below 3.10 doesn't support kw_only
        return dataclass(frozen=True)(cls)  # pragma: no cover
    else:
        return dataclass(frozen=True, kw_only=True)(cls)


@command_helper
class NeedsContext:
    context: Dict[str, Any] = field(default_factory=dict)  # pylint: disable=invalid-field-call


@dataclass(frozen=True)
class WalletClientInfo:
    client: WalletRpcClient
    fingerprint: int
    config: Dict[str, Any]


@command_helper
class NeedsWalletRPC(NeedsContext):
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
            if "root_path" not in kwargs:
                kwargs["root_path"] = self.context["root_path"]  # pylint: disable=unsubscriptable-object
            async with get_wallet_client(self.wallet_rpc_port, self.fingerprint, **kwargs) as (
                wallet_client,
                fp,
                config,
            ):
                yield WalletClientInfo(wallet_client, fp, config)
