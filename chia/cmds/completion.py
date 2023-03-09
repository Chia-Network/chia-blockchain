from __future__ import annotations

import os
import subprocess

import click

SHELLS = ["bash", "zsh", "fish"]
shell = os.environ.get("SHELL", "").split("/")[-1]
cmd = f"_CHIA_COMPLETE={shell}_source chia"


@click.group(
    short_help="Generate shell completion",
)
def completion() -> None:
    pass


@completion.command(short_help="Generate shell completion code")
@click.option(
    "-s",
    "--shell",
    type=click.Choice(SHELLS),
    default=shell,
    show_default=False,
    required=False,
    help="Shell type to generate for",
)
def generate(shell: str) -> None:
    """
    \b
    Generate shell completion code for the current, or specified (-s)hell.
    You will need to 'source' this code to enable shell completion.
    You can source it directly (performs slower) by running:
        \033[3;33meval "$(chia complete generate)"\033[0m
    or you can save the output to a file:
        \033[3;33mchia complete generate > ~/.chia-complete-bash\033[0m
    and source that file with:
        \033[3;33m. ~/.chia-complete-bash\033[0m
    """
    subprocess.run(cmd, shell=True, check=True)
