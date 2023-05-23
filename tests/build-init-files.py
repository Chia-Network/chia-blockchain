#!/usr/bin/env python3

# Create missing `__init__.py` files in the source code folders (in "chia/" and "tests/").
#
# They are required by the python interpreter to properly identify modules/packages so that tools like `mypy` or an IDE
# can work with their full capabilities.
#
# See https://docs.python.org/3/tutorial/modules.html#packages.
#
# Note: This script is run in a `pre-commit` hook (which runs on CI) to make sure we don't miss out any folder.

from __future__ import annotations

import logging
import pathlib
import sys

import click

log_levels = {
    0: logging.ERROR,
    1: logging.WARNING,
    2: logging.INFO,
}


ignores = {"__pycache__", ".pytest_cache"}


@click.command()
@click.option(
    "-r", "--root", "root_str", type=click.Path(dir_okay=True, file_okay=False, resolve_path=True), default="."
)
@click.option("-v", "--verbose", count=True, help=f"Increase verbosity up to {len(log_levels) - 1} times")
def command(verbose, root_str):
    logger = logging.getLogger()
    log_level = log_levels.get(verbose, min(log_levels.values()))
    logger.setLevel(log_level)
    stream_handler = logging.StreamHandler()
    logger.addHandler(stream_handler)

    tree_roots = ["benchmarks", "build_scripts", "chia", "tests", "tools"]
    failed = False
    root = pathlib.Path(root_str).resolve()
    directories = sorted(
        path
        for tree_root in tree_roots
        for path in root.joinpath(tree_root).rglob("**/")
        if all(part not in ignores for part in path.parts)
    )

    for path in directories:
        init_path = path.joinpath("__init__.py")
        # This has plenty of race hazards. If it messes up,
        # it will likely get caught the next time.
        if init_path.is_file() and not init_path.is_symlink():
            logger.info(f"Found   : {init_path}")
            continue
        elif not init_path.exists():
            failed = True
            init_path.touch()
            logger.warning(f"Created : {init_path}")
        else:
            failed = True
            logger.error(f"Fail    : present but not a regular file: {init_path}", file=sys.stderr)

    if failed:
        raise click.ClickException("At least one __init__.py created or not a regular file")


command()  # pylint: disable=no-value-for-parameter
