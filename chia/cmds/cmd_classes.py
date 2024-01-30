from __future__ import annotations

import asyncio
import inspect
import sys
from contextlib import asynccontextmanager
from dataclasses import MISSING, dataclass, field, fields
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Protocol, Type, Union, get_type_hints

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


@dataclass(frozen=True)
class _CommandParsingStage:
    my_dataclass: Type[ChiaCommand]
    my_option_decorators: List[Callable[[SyncCmd], SyncCmd]]
    my_subclasses: Dict[str, _CommandParsingStage]
    my_kwarg_names: List[str]
    _needs_context: bool

    def needs_context(self) -> bool:
        if self._needs_context:
            return True
        else:
            return any([subclass.needs_context() for subclass in self.my_subclasses.values()])

    def get_all_option_decorators(self) -> List[Callable[[SyncCmd], SyncCmd]]:
        all_option_decorators: List[Callable[[SyncCmd], SyncCmd]] = self.my_option_decorators
        for subclass in self.my_subclasses.values():
            all_option_decorators.extend(subclass.get_all_option_decorators())
        return all_option_decorators

    def initialize_instance(self, **kwargs: Any) -> ChiaCommand:
        kwargs_to_pass: Dict[str, Any] = {}
        for kwarg_name in self.my_kwarg_names:
            kwargs_to_pass[kwarg_name] = kwargs[kwarg_name]

        for subclass_arg_name, subclass in self.my_subclasses.items():
            kwargs_to_pass[subclass_arg_name] = subclass.initialize_instance(**kwargs)

        return self.my_dataclass(**kwargs_to_pass)

    def apply_decorators(self, cmd: SyncCmd) -> SyncCmd:
        cmd_to_return = cmd
        if self.needs_context():

            def strip_click_context(func: SyncCmd) -> SyncCmd:
                def _inner(ctx: click.Context, **kwargs: Any) -> None:
                    context: Dict[str, Any] = ctx.obj if ctx.obj is not None else {}
                    func(context=context, **kwargs)

                return _inner

            cmd_to_return = click.pass_context(strip_click_context(cmd_to_return))

        for decorator in self.get_all_option_decorators():
            cmd_to_return = decorator(cmd_to_return)

        return cmd_to_return


def _generate_command_parser(cls: Type[ChiaCommand]) -> _CommandParsingStage:
    option_decorators: List[Callable[[SyncCmd], SyncCmd]] = []
    kwarg_names: List[str] = []
    subclasses: Dict[str, _CommandParsingStage] = {}
    needs_context: bool = False

    hints = get_type_hints(cls)
    _fields = fields(cls)  # type: ignore[arg-type]

    for _field in _fields:
        field_name = _field.name
        if isinstance(hints[field_name], type) and issubclass(hints[field_name], _CommandHelper):
            subclasses[field_name] = _generate_command_parser(hints[field_name])
        else:
            if field_name == "context":
                if hints[field_name] != Context:
                    raise ValueError("only Context can be the hint for variables named 'context'")
                else:
                    needs_context = True
                    kwarg_names.append(field_name)
                    continue
            elif "is_command_option" not in _field.metadata or not _field.metadata["is_command_option"]:
                continue

            kwarg_names.append(field_name)
            option_decorators.append(
                click.option(
                    *_field.metadata["param_decls"],
                    **{k: v for k, v in _field.metadata.items() if k not in ("param_decls", "is_command_option")},
                )
            )

    return _CommandParsingStage(
        cls,
        option_decorators,
        subclasses,
        kwarg_names,
        needs_context,
    )


def _convert_class_to_function(cls: Type[ChiaCommand]) -> SyncCmd:
    command_parser = _generate_command_parser(cls)

    if inspect.iscoroutinefunction(cls.run):

        async def async_base_cmd(*args: Any, **kwargs: Any) -> None:
            await command_parser.initialize_instance(*args, **kwargs).run()  # type: ignore[misc]

        def base_cmd(*args: Any, **kwargs: Any) -> None:
            coro = async_base_cmd(*args, **kwargs)
            assert coro is not None
            asyncio.run(coro)

    else:

        def base_cmd(*args: Any, **kwargs: Any) -> None:
            command_parser.initialize_instance(*args, **kwargs).run()

    return command_parser.apply_decorators(base_cmd)


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

        cmd.command(name, help=help)(_convert_class_to_function(wrapped_cls))
        return wrapped_cls

    return _chia_command


class _CommandHelper:
    pass


@dataclass_transform()
def command_helper(cls: Type[Any]) -> Type[Any]:
    if sys.version_info < (3, 10):  # stuff below 3.10 doesn't support kw_only
        return dataclass(frozen=True)(
            type(cls.__name__, (dataclass(frozen=True)(cls), _CommandHelper), {})
        )  # pragma: no cover
    else:
        return dataclass(frozen=True, kw_only=True)(
            type(cls.__name__, (dataclass(frozen=True, kw_only=True)(cls), _CommandHelper), {})
        )


Context = Dict[str, Any]


@dataclass(frozen=True)
class WalletClientInfo:
    client: WalletRpcClient
    fingerprint: int
    config: Dict[str, Any]


@command_helper
class NeedsWalletRPC:
    context: Context = field(default_factory=dict)  # pylint: disable=invalid-field-call
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
