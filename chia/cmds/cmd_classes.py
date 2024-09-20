from __future__ import annotations

import asyncio
import collections
import inspect
import sys
from contextlib import asynccontextmanager
from dataclasses import MISSING, dataclass, field, fields
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Type,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

import click
from typing_extensions import dataclass_transform

from chia.cmds.cmds_util import get_wallet_client
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.streamable import is_type_SpecificOptional

SyncCmd = Callable[..., None]

COMMAND_HELPER_ATTRIBUTE_NAME = "_is_command_helper"


class SyncChiaCommand(Protocol):
    def run(self) -> None: ...


class AsyncChiaCommand(Protocol):
    async def run(self) -> None: ...


ChiaCommand = Union[SyncChiaCommand, AsyncChiaCommand]


def option(*param_decls: str, **kwargs: Any) -> Any:
    if sys.version_info < (3, 10):  # versions < 3.10 don't know about kw_only and they complain about lacks of defaults
        # Can't get coverage on this because we only test on one version
        default_default = None  # pragma: no cover
    else:
        default_default = MISSING

    return field(  # pylint: disable=invalid-field-call
        metadata=dict(
            option_args=dict(
                param_decls=tuple(param_decls),
                **kwargs,
            ),
        ),
        default=kwargs.get("default", default_default),
    )


class HexString(click.ParamType):
    name = "hexstring"

    def convert(self, value: str, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> bytes:
        if isinstance(value, bytes):  # This if is due to some poor handling on click's part
            return value
        try:
            return hexstr_to_bytes(value)
        except ValueError as e:
            self.fail(f"not a valid hex string: {value!r} ({e})", param, ctx)


class HexString32(click.ParamType):
    name = "hexstring32"

    def convert(self, value: str, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> bytes32:
        if isinstance(value, bytes32):  # This if is due to some poor handling on click's part
            return value
        try:
            return bytes32.from_hexstr(value)
        except ValueError as e:
            self.fail(f"not a valid 32-byte hex string: {value!r} ({e})", param, ctx)


_CLASS_TYPES_TO_CLICK_TYPES = {
    bytes: HexString(),
    bytes32: HexString32(),
}


@dataclass
class _CommandParsingStage:
    my_dataclass: Type[ChiaCommand]
    my_option_decorators: List[Callable[[SyncCmd], SyncCmd]]
    my_members: Dict[str, _CommandParsingStage]
    my_kwarg_names: List[str]
    _needs_context: bool

    def needs_context(self) -> bool:
        if self._needs_context:
            return True
        else:
            return any(member.needs_context() for member in self.my_members.values())

    def get_all_option_decorators(self) -> List[Callable[[SyncCmd], SyncCmd]]:
        all_option_decorators: List[Callable[[SyncCmd], SyncCmd]] = self.my_option_decorators
        for member in self.my_members.values():
            all_option_decorators.extend(member.get_all_option_decorators())
        return all_option_decorators

    def initialize_instance(self, **kwargs: Any) -> ChiaCommand:
        kwargs_to_pass: Dict[str, Any] = {}
        for kwarg_name in self.my_kwarg_names:
            kwargs_to_pass[kwarg_name] = kwargs[kwarg_name]

        for member_arg_name, member in self.my_members.items():
            kwargs_to_pass[member_arg_name] = member.initialize_instance(**kwargs)

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

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        instance = self.initialize_instance(*args, **kwargs)
        if inspect.iscoroutinefunction(self.my_dataclass.run):
            coro = instance.run()
            assert coro is not None
            asyncio.run(coro)
        else:
            instance.run()


def _generate_command_parser(cls: Type[ChiaCommand]) -> _CommandParsingStage:
    option_decorators: List[Callable[[SyncCmd], SyncCmd]] = []
    kwarg_names: List[str] = []
    members: Dict[str, _CommandParsingStage] = {}
    needs_context: bool = False

    hints = get_type_hints(cls)
    _fields = fields(cls)  # type: ignore[arg-type]

    for _field in _fields:
        field_name = _field.name
        if getattr(hints[field_name], COMMAND_HELPER_ATTRIBUTE_NAME, False):
            members[field_name] = _generate_command_parser(hints[field_name])
        elif field_name == "context":
            if hints[field_name] != Context:
                raise ValueError("only Context can be the hint for variables named 'context'")
            else:
                needs_context = True
                kwarg_names.append(field_name)
        elif "option_args" in _field.metadata:
            option_args: Dict[str, Any] = {"multiple": False, "required": False}
            option_args.update(_field.metadata["option_args"])

            if "type" not in option_args:
                origin = get_origin(hints[field_name])
                if origin == collections.abc.Sequence:
                    if not option_args["multiple"]:
                        raise TypeError("Can only use Sequence with multiple=True")
                    else:
                        type_arg = get_args(hints[field_name])[0]
                        if "default" in option_args and (
                            not isinstance(option_args["default"], tuple)
                            or any(not isinstance(item, type_arg) for item in option_args["default"])
                        ):
                            raise TypeError(
                                f"Default {option_args['default']} is not a tuple "
                                f"or all of its elements are not of type {type_arg}"
                            )
                elif option_args["multiple"]:
                    raise TypeError("Options with multiple=True must be Sequence[T]")
                elif is_type_SpecificOptional(hints[field_name]):
                    if option_args["required"]:
                        raise TypeError("Optional only allowed for options with required=False")
                    type_arg = get_args(hints[field_name])[0]
                    if "default" in option_args and (
                        not isinstance(option_args["default"], type_arg) and option_args["default"] is not None
                    ):
                        raise TypeError(f"Default {option_args['default']} is not type {type_arg} or None")
                elif origin is not None:
                    raise TypeError(f"Type {origin} invalid as a click type")
                else:
                    if hints[field_name] in _CLASS_TYPES_TO_CLICK_TYPES:
                        type_arg = _CLASS_TYPES_TO_CLICK_TYPES[hints[field_name]]
                    else:
                        type_arg = hints[field_name]
                    if "default" in option_args and not isinstance(option_args["default"], hints[field_name]):
                        raise TypeError(f"Default {option_args['default']} is not type {type_arg}")
            else:
                type_arg = option_args["type"]

            kwarg_names.append(field_name)
            option_decorators.append(
                click.option(
                    *option_args["param_decls"],
                    type=type_arg,
                    **{k: v for k, v in option_args.items() if k not in ("param_decls", "type")},
                )
            )

    return _CommandParsingStage(
        my_dataclass=cls,
        my_option_decorators=option_decorators,
        my_members=members,
        my_kwarg_names=kwarg_names,
        _needs_context=needs_context,
    )


def _convert_class_to_function(cls: Type[ChiaCommand]) -> SyncCmd:
    command_parser = _generate_command_parser(cls)

    return command_parser.apply_decorators(command_parser)


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

        cmd.command(name, short_help=help)(_convert_class_to_function(wrapped_cls))
        return wrapped_cls

    return _chia_command


@dataclass_transform()
def command_helper(cls: Type[Any]) -> Type[Any]:
    if sys.version_info < (3, 10):  # stuff below 3.10 doesn't support kw_only
        new_cls = dataclass(frozen=True)(cls)  # pragma: no cover
    else:
        new_cls = dataclass(frozen=True, kw_only=True)(cls)
    setattr(new_cls, COMMAND_HELPER_ATTRIBUTE_NAME, True)
    return new_cls


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
