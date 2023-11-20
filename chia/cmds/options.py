from __future__ import annotations

from typing import Any, Callable, TypeVar, Union

import click

from chia.cmds.param_types import TRANSACTION_FEE
from chia.util.ints import uint64

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


def create_fee(message: str = "Set the fees for the transaction, in XCH", required: bool = True) -> Callable[[FC], FC]:
    return click.option(
        "-m",
        "--fee",
        help=message,
        type=TRANSACTION_FEE,
        default=uint64(0),
        show_default=True,
        required=required,
    )
