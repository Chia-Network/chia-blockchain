#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path
from subprocess import CalledProcessError, run
from typing import List, cast

import click

file_path = Path(__file__)
here = file_path.parent
exclusion_file = here.joinpath("mypy-exclusions.txt")


def write_file(path: Path, content: str) -> None:
    with path.open(mode="w", encoding="utf-8", newline="\n") as file:
        file.write(content.strip() + "\n")


def get_mypy_failures() -> List[str]:
    # Get a list of all mypy failures when only running mypy with the template file `mypy.ini.template`
    command = [sys.executable, "activated.py", "mypy", "--config-file", "mypy.ini.template"]
    try:
        run(command, capture_output=True, check=True, encoding="utf-8")
    except CalledProcessError as e:
        if e.returncode == 1:
            return cast(List[str], e.stdout.splitlines())
        raise click.ClickException(f"Unexpected mypy failure:\n{e.stderr}") from e
    return []


def split_mypy_failure(line: str) -> List[str]:
    return list(Path(line[: line.find(".py")]).parts)


def build_exclusion_list(mypy_failures: List[str]) -> List[str]:
    # Create content for `mypy-exclusions.txt` from a list of mypy failures which look like:
    #     # chia/cmds/wallet_funcs.py:1251: error: Incompatible types in assignment (expression has type "str", variable has type "int")  [assignment] # noqa
    return sorted({".".join(split_mypy_failure(line)) for line in mypy_failures[:-1]})


@click.group()
def main() -> None:
    pass


@main.command()
@click.option("--check-exclusions/--no-check-exclusions", show_default=True, envvar="CHIA_MANAGE_MYPY_CHECK_EXCLUSIONS")
def build_mypy_ini(check_exclusions: bool = False) -> None:
    if not exclusion_file.exists():
        raise click.ClickException(f"{exclusion_file.name} missing, run `{file_path.name} build-exclusions`")
    exclusion_file_content = exclusion_file.read_text(encoding="utf-8").splitlines()
    exclusion_lines = [line for line in exclusion_file_content if not line.startswith("#") and len(line.strip()) > 0]
    if check_exclusions:
        mypy_failures = get_mypy_failures()
        updated_exclusions = build_exclusion_list(mypy_failures)
        # Compare the old content with the new content and fail if some file without issues is excluded.
        updated_set = set(updated_exclusions)
        old_set = set(exclusion_lines)
        if updated_set != old_set:
            fixed = "\n".join(f"  -> {entry}" for entry in sorted(old_set - updated_set))
            if len(fixed) > 0:
                raise click.ClickException(
                    f"The following fixed files need to be dropped from {exclusion_file.name}:\n{fixed}"
                )
            new_exclusions = sorted(updated_set - old_set)
            new_failures = sorted(
                line.strip()
                for line in mypy_failures
                if any(exclusion.split(".") == split_mypy_failure(line) for exclusion in new_exclusions)
            )
            if len(new_failures) > 0:
                new_failures_string = "\n".join(new_failures)
                raise click.ClickException(f"The following new issues have been introduced:\n{new_failures_string}")

    # Create the `mypy.ini` with all entries from `mypy-exclusions.txt`
    exclusion_section = f"[mypy-{','.join(exclusion_lines)}]"
    mypy_config_data = (
        here.joinpath("mypy.ini.template")
        .read_text(encoding="utf-8")
        .replace("[mypy-chia-exclusions]", exclusion_section)
    )
    write_file(here.joinpath("mypy.ini"), mypy_config_data)


@main.command()
def build_exclusions() -> None:
    updated_file_content = [
        f"# File created by: python {file_path.name} build-exclusions",
        *build_exclusion_list(get_mypy_failures()),
    ]
    write_file(exclusion_file, "\n".join(updated_file_content))


sys.exit(main())
