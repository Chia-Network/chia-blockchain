from __future__ import annotations

import os
import subprocess
from pathlib import Path

import click

SHELLS = ["bash", "zsh", "fish"]
shell = os.environ.get("SHELL")

if shell is not None:
    shell = Path(shell).name
    if shell not in SHELLS:
        shell = None


@click.group(
    help="Generate shell completion",
)
def completion() -> None:
    pass


@completion.command(help="Generate shell completion code")
@click.option(
    "-s",
    "--shell",
    type=click.Choice(SHELLS),
    default=shell,
    show_default=True,
    required=shell is None,
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
    # Could consider calling directly in the future.
    # https://github.com/pallets/click/blob/ef11be6e49e19a055fe7e5a89f0f1f4062c68dba/src/click/shell_completion.py#L17
    subprocess.run(["chia"], check=True, env={**os.environ, "_CHIA_COMPLETE": f"{shell}_source"})
