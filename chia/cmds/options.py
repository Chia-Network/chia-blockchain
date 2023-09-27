from __future__ import annotations

from typing import Any, Callable, TypeVar, Union

import click

FC = TypeVar("FC", bound=Union[Callable[..., Any], click.Command])


def create_fingerprint(required: bool = False) -> Callable[[FC], FC]:
    return click.option(
        "-f",
        "--fingerprint",
        help="Fingerprint of the wallet to use",
        required=required,
        # TODO: should be uint32
        type=int,
    )
