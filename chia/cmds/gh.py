from __future__ import annotations

import shlex
from typing import Literal, Optional, Union

import anyio
import click
import yaml

from chia.cmds.cmd_classes import chia_command, option


@click.group("gh", help="For working with GitHub")
def gh_group() -> None:
    pass


@chia_command(
    gh_group,
    name="test",
    # TODO: welp, yeah, help
    help="",
    # short_help="helpy help",
    # help="""docstring help
    # and
    # more
    # lines
    #
    # blue
    # """,
)
class TestCMD:
    owner: str = option("-o", "--owner", help="Owner of the repo", type=str, default="Chia-Network")
    repository: str = option("-r", "--repository", help="Repository name", type=str, default="chia-blockchain")
    ref: Optional[str] = option("-f", "--ref", help="Branch or tag name (commit SHA not supported", type=str)
    per: Union[Literal["directory"], Literal["file"]] = option(
        "-p", "--per", help="Per", type=click.Choice(["directory", "file"]), default="directory"
    )
    only: Optional[str] = option("-o", "--only", help="Only run this item", type=str)
    duplicates: int = option("-d", "--duplicates", help="Number of duplicates", type=int, default=1)
    run_linux: bool = option("--run-linux/--skip-linux", help="Run on Linux", default=True)
    run_macos_intel: bool = option("--run-macos-intel/--skip-macos-intel", help="Run on macOS Intel", default=True)
    run_macos_arm: bool = option("--run-macos-arm/--skip-macos-arm", help="Run on macOS ARM", default=True)
    run_windows: bool = option("--run-windows/--skip-windows", help="Run on Windows", default=True)
    full_python_matrix: bool = option(
        "--full-python-matrix/--default-python-matrix", help="Run on all Python versions", default=False
    )

    async def run(self) -> None:
        def input_arg(name: str, value: object, cond: bool = True) -> list[str]:
            dumped = yaml.safe_dump(value).partition("\n")[0]
            return ["-f", f"inputs[{name}]={dumped}"] if cond else []

        workflow_id = "test.yml"

        if self.ref is None:
            process = await anyio.run_process(
                command=["git", "rev-parse", "--abbrev-ref", "HEAD"], check=False, stderr=None
            )
            if process.returncode != 0:
                raise click.ClickException("Failed to get current branch")
            ref = process.stdout.decode(encoding="utf-8").strip()
        else:
            ref = self.ref

        command = [
            "gh",
            "api",
            "--method",
            "POST",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
            f"/repos/{self.owner}/{self.repository}/actions/workflows/{workflow_id}/dispatches",
            "-f",
            f"ref={ref}",
            *input_arg("per", self.per),
            *input_arg("only", self.only, self.only is not None),
            *input_arg("duplicates", self.duplicates),
            *input_arg("run-linux", self.run_linux),
            *input_arg("run-macos-intel", self.run_macos_intel),
            *input_arg("run-macos-arm", self.run_macos_arm),
            *input_arg("run-windows", self.run_windows),
            *input_arg("full-python-matrix", self.full_python_matrix),
        ]

        print(f"running command: {shlex.join(command)}")
        process = await anyio.run_process(command=command, check=False, stdout=None, stderr=None)
        if process.returncode != 0:
            raise click.ClickException("Failed to dispatch workflow")
