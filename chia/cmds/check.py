from __future__ import annotations

import click

from chia.cmds.check_func import check_shielding


@click.group(name="check", help="Project checks such as might be run in CI")
def check_group() -> None:
    pass


@check_group.command(name="shielding")
def shielding_command() -> None:
    count = check_shielding()

    message = f"{count} concerns found"
    if count > 0:
        raise click.ClickException(message)
    else:
        print(message)
