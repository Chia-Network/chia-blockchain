from __future__ import annotations

import asyncio
import collections
import dataclasses
import inspect
import pathlib
import sys
from dataclasses import MISSING, dataclass, field, fields
from typing import (
    Any,
    Callable,
    ClassVar,
    Optional,
    Protocol,
    Union,
    final,
    get_args,
    get_origin,
    get_type_hints,
)

import click
from chia_rs.sized_bytes import bytes32
from typing_extensions import dataclass_transform

from chia.util.byte_types import hexstr_to_bytes
from chia.util.default_root import DEFAULT_KEYS_ROOT_PATH, DEFAULT_ROOT_PATH
from chia.util.streamable import is_type_SpecificOptional

SyncCmd = Callable[..., None]

COMMAND_HELPER_ATTRIBUTE_NAME = "_is_command_helper"


class SyncChiaCommand(Protocol):
    def run(self) -> None: ...


class AsyncChiaCommand(Protocol):
    async def run(self) -> None: ...


ChiaCommand = Union[SyncChiaCommand, AsyncChiaCommand]


def option(*param_decls: str, **kwargs: Any) -> Any:
    if sys.version_info >= (3, 10):
        default_default = MISSING
    else:  # versions < 3.10 don't know about kw_only and they complain about lacks of defaults
        # Can't get coverage on this because we only test on one version
        default_default = None  # pragma: no cover

    return field(
        metadata=dict(
            option_args=dict(
                param_decls=tuple(param_decls),
                **kwargs,
            ),
        ),
        default=kwargs.get("default", default_default),
    )


@final
@dataclasses.dataclass
class ChiaCliContext:
    context_dict_key: ClassVar[str] = "_chia_cli_context"

    root_path: pathlib.Path = DEFAULT_ROOT_PATH
    keys_root_path: pathlib.Path = DEFAULT_KEYS_ROOT_PATH
    expected_prefix: Optional[str] = None
    rpc_port: Optional[int] = None
    keys_fingerprint: Optional[int] = None
    keys_filename: Optional[str] = None
    expected_address_prefix: Optional[str] = None

    @classmethod
    def set_default(cls, ctx: click.Context) -> ChiaCliContext:
        ctx.ensure_object(dict)
        self = ctx.obj.setdefault(cls.context_dict_key, cls())
        assert isinstance(self, cls)
        return self

    def to_click(self) -> dict[str, object]:
        return {self.context_dict_key: self}


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
    my_dataclass: type[ChiaCommand]
    my_option_decorators: list[Callable[[SyncCmd], SyncCmd]]
    my_members: dict[str, _CommandParsingStage]
    my_kwarg_names: list[str]
    _needs_context: bool

    def needs_context(self) -> bool:
        if self._needs_context:
            return True
        else:
            return any(member.needs_context() for member in self.my_members.values())

    def get_all_option_decorators(self) -> list[Callable[[SyncCmd], SyncCmd]]:
        all_option_decorators: list[Callable[[SyncCmd], SyncCmd]] = self.my_option_decorators
        for member in self.my_members.values():
            all_option_decorators.extend(member.get_all_option_decorators())
        return all_option_decorators

    def initialize_instance(self, **kwargs: Any) -> ChiaCommand:
        kwargs_to_pass: dict[str, Any] = {}
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
                    context = ChiaCliContext.set_default(ctx)
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


def _generate_command_parser(cls: type[ChiaCommand]) -> _CommandParsingStage:
    option_decorators: list[Callable[[SyncCmd], SyncCmd]] = []
    kwarg_names: list[str] = []
    members: dict[str, _CommandParsingStage] = {}
    needs_context: bool = False

    hints = get_type_hints(cls)
    _fields = fields(cls)  # type: ignore[arg-type]

    for _field in _fields:
        field_name = _field.name
        if getattr(hints[field_name], COMMAND_HELPER_ATTRIBUTE_NAME, False):
            members[field_name] = _generate_command_parser(hints[field_name])
        elif field_name == "context":
            if hints[field_name] != ChiaCliContext:
                raise ValueError("only Context can be the hint for variables named 'context'")
            else:
                needs_context = True
                kwarg_names.append(field_name)
        elif "option_args" in _field.metadata:
            option_args: dict[str, Any] = {"multiple": False, "required": False}
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
                    field_name,
                    type=type_arg,
                    **{k: v for k, v in option_args.items() if k not in {"param_decls", "type"}},
                )
            )

    return _CommandParsingStage(
        my_dataclass=cls,
        my_option_decorators=option_decorators,
        my_members=members,
        my_kwarg_names=kwarg_names,
        _needs_context=needs_context,
    )


def _convert_class_to_function(cls: type[ChiaCommand]) -> SyncCmd:
    command_parser = _generate_command_parser(cls)

    return command_parser.apply_decorators(command_parser)


@dataclass_transform(frozen_default=True)
def chia_command(
    *,
    group: Optional[click.Group] = None,
    name: str,
    short_help: str,
    help: str,
) -> Callable[[type[ChiaCommand]], type[ChiaCommand]]:
    def _chia_command(cls: type[ChiaCommand]) -> type[ChiaCommand]:
        # The type ignores here are largely due to the fact that the class information is not preserved after being
        # passed through the dataclass wrapper.  Not sure what to do about this right now.
        if sys.version_info >= (3, 10):
            wrapped_cls: type[ChiaCommand] = dataclass(
                frozen=True,
                kw_only=True,
            )(cls)
        else:  # pragma: no cover
            # stuff below 3.10 doesn't know about kw_only
            wrapped_cls: type[ChiaCommand] = dataclass(
                frozen=True,
            )(cls)

        metadata = Metadata(
            command=click.command(
                name=name,
                short_help=short_help,
                help=help,
            )(_convert_class_to_function(wrapped_cls))
        )

        setattr(wrapped_cls, _chia_command_metadata_attribute, metadata)
        if group is not None:
            group.add_command(metadata.command)

        return wrapped_cls

    return _chia_command


_chia_command_metadata_attribute = f"_{__name__.replace('.', '_')}_{chia_command.__qualname__}_metadata"


@dataclass(frozen=True)
class Metadata:
    command: click.Command


def get_chia_command_metadata(cls: type[ChiaCommand]) -> Metadata:
    metadata: Optional[Metadata] = getattr(cls, _chia_command_metadata_attribute, None)
    if metadata is None:
        raise Exception(f"Class is not a chia command: {cls}")

    return metadata


@dataclass_transform(frozen_default=True)
def command_helper(cls: type[Any]) -> type[Any]:
    if sys.version_info >= (3, 10):
        new_cls = dataclass(frozen=True, kw_only=True)(cls)
    else:  # stuff below 3.10 doesn't support kw_only
        new_cls = dataclass(frozen=True)(cls)  # pragma: no cover
    setattr(new_cls, COMMAND_HELPER_ATTRIBUTE_NAME, True)
    return new_cls
