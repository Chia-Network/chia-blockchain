from __future__ import annotations

import click

from chia.cmds.check_func import check_shielding


@click.group(name="check", help="Project checks such as might be run in CI")
def check_group() -> None:
    pass


@check_group.command(name="shielding")
@click.option("--use-file-ignore/--no-file-ignore", default=True)
def shielding_command(use_file_ignore: bool) -> None:
    count = check_shielding(use_file_ignore=use_file_ignore)

    message = f"{count} concerns found"
    if count > 0:
        raise click.ClickException(message)
    else:
        print(message)
