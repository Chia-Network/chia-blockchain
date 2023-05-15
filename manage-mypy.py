#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path
from subprocess import run
from typing import List

import click

file_path = Path(__file__)
here = file_path.parent
exclusion_file = here / "mypy-exclusions.txt"


def build_exclusion_list() -> List[str]:
    # Create content for `mypy-exclusions.txt` based on a `mypy` run with `mypy.ini.template`
    command = ["python", "activated.py", "mypy", "--config-file", "mypy.ini.template"]
    lines = run(command, capture_output=True, encoding="utf-8").stdout.splitlines()
    return sorted({".".join(Path(line[: line.find(".py")]).parts) for line in lines[0 : len(lines) - 1]})


@click.group()
def main() -> None:
    pass


@main.command()
@click.option("--check-exclusions/--no-check-exclusions", show_default=True, envvar="CHIA_MANAGE_MYPY_CHECK_EXCLUSIONS")
def build_mypy_ini(check_exclusions: bool = False) -> None:
    if not exclusion_file.exists():
        raise click.ClickException(f"{exclusion_file.name} missing, run with `{file_path.name}`")
    if check_exclusions:
        updated_exclusions = build_exclusion_list()
        # Compare the old content with the new content and fail if some file without issues is excluded.
        old_exclusions = exclusion_file.read_text(encoding="utf-8").splitlines()[1:]
        if updated_exclusions != old_exclusions:
            fixed = "\n".join(f"  -> {entry}" for entry in sorted(set(old_exclusions) - set(updated_exclusions)))
            if len(fixed) > 0:
                raise click.ClickException(
                    f"The following fixed files need to be dropped from {exclusion_file.name}:\n{fixed}"
                )

    # Create the `mypy.ini` with all entries from `mypy-exclusions.txt`
    exclusion_file_content = exclusion_file.read_text(encoding="utf-8").splitlines()
    exclusion_lines = [line for line in exclusion_file_content if not line.startswith("#") and len(line.strip()) > 0]
    exclusion_section = f"[mypy-{','.join(exclusion_lines)}]"
    mypy_config_data = (
        here.joinpath("mypy.ini.template")
        .read_text(encoding="utf-8")
        .replace("[mypy-chia-exclusions]", exclusion_section)
    )
    mypy_config_path = here / "mypy.ini"
    mypy_config_path.touch()
    mypy_config_path.write_text(mypy_config_data.strip() + "\n", encoding="utf-8", newline="\n")


@main.command()
def build_exclusions() -> None:
    exclusion_file.touch()
    updated_file_content = [
        f"# File created by: python {file_path.name} build-exclusions",
        *build_exclusion_list(),
    ]
    exclusion_file.write_text("\n".join(updated_file_content) + "\n", encoding="utf-8", newline="\n")


sys.exit(main())
