from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence, TypeVar, Union

# lgtm is expecting us to be misusing the code such that click would not refer to the
# regular click package.
import click  # lgtm [py/import-own-module]

F = TypeVar("F", bound=Callable[..., Any])
CmdType = TypeVar("CmdType", bound=click.Command)


class _Group(click.Group):
    def __init__(
        self,
        name: Optional[str] = None,
        commands: Optional[Union[Dict[str, _Command], Sequence[_Command]]] = None,
        **attrs: Any,
    ) -> None:
        # TODO: remove ignore after we get https://github.com/pallets/click/pull/2265
        super().__init__(name=name, commands=commands, **attrs)  # type: ignore[arg-type]
        self.command_class = _Command

    def main(
        self,
        args: Optional[Sequence[str]] = None,
        prog_name: Optional[str] = None,
        complete_var: Optional[str] = None,
        standalone_mode: bool = True,
        **extra: Any,
    ) -> Any:
        return super().main(
            args=args,
            prog_name=prog_name,
            complete_var=complete_var,
            standalone_mode=standalone_mode,
            windows_expand_args=True,
            **extra,
        )


class _Command(click.Command):
    def main(
        self,
        args: Optional[Sequence[str]] = None,
        prog_name: Optional[str] = None,
        complete_var: Optional[str] = None,
        standalone_mode: bool = True,
        **extra: Any,
    ) -> Any:
        return super().main(
            args=args,
            prog_name=prog_name,
            complete_var=complete_var,
            standalone_mode=standalone_mode,
            windows_expand_args=True,
            **extra,
        )


def command(
    name: Optional[str] = None,
    **attrs: Any,
) -> Callable[[F], _Command]:
    # TODO: I believe that this can be resolved and is related to the order of the
    #       overloads for click.command()
    return click.command(name=name, cls=_Command, **attrs)  # type: ignore[return-value]


def group(name: Optional[str] = None, **attrs: Any) -> Callable[[F], _Group]:
    # TODO: I believe that this can be resolved and is related to the order of the
    #       overloads for click.group()
    return click.group(name=name, cls=_Group, **attrs)  # type: ignore[return-value]
