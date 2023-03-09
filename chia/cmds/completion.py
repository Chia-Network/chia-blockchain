from __future__ import annotations

import os
import subprocess

import click

SHELLS = ['bash', 'zsh', 'fish']

@click.group()
def completion() -> None:
    pass


@completion.command()
@click.option(
    "-s",
    "--shell",
    type=click.Choice(SHELLS),
    default=os.environ.get('SHELL', '').split('/')[-1],
    show_default=False,
    required=True,
    help="Shell type to generate completion for",
)
def generate(shell: str) -> None:
    """
    Generate shell completion script
    """
    if shell is None:
        shell = os.environ.get('SHELL', '').split('/')[-1]
    if shell not in SHELLS:
        raise click.UsageError(f'Invalid shell type: {shell}')
    cmd = f'_CHIA_COMPLETE={shell}_source chia'
    print("Save the following output as '~/.chia-completion."+shell+"' and source it according to your shell:\n")
    subprocess.run(cmd, shell=True, check=True)
