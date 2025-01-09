from __future__ import annotations

import json
import os
import shlex
import urllib
import uuid
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Callable, ClassVar, Literal, Optional, Union, overload

import anyio
import click
import yaml

from chia.cmds.cmd_classes import chia_command, option


class UnexpectedFormError(Exception):
    pass


Oses = Union[Literal["linux"], Literal["macos-arm"], Literal["macos-intel"], Literal["windows"]]
Method = Union[Literal["GET"], Literal["POST"]]
Per = Union[Literal["directory"], Literal["file"]]

all_oses: Sequence[Oses] = ("linux", "macos-arm", "macos-intel", "windows")


def report(*args: str) -> None:
    print("    ====", *args)


async def get_gh_token() -> str:
    command = ["gh", "auth", "token"]
    report(f"running command: {shlex.join(command)}")
    process = await anyio.run_process(command=command, check=False, stderr=None)

    if process.returncode != 0:
        raise click.ClickException("failed to get gh cli personal access token")

    return process.stdout.decode("utf-8").strip()


@overload
async def run_gh_api(method: Method, args: list[str], error: str) -> None: ...
@overload
async def run_gh_api(method: Method, args: list[str], error: str, capture_stdout: Literal[False]) -> None: ...
@overload
async def run_gh_api(method: Method, args: list[str], error: str, capture_stdout: Literal[True]) -> str: ...


async def run_gh_api(method: Method, args: list[str], error: str, capture_stdout: bool = False) -> Optional[str]:
    command = [
        "gh",
        "api",
        f"--method={method}",
        "-H=Accept: application/vnd.github+json",
        "-H=X-GitHub-Api-Version: 2022-11-28",
        *args,
    ]
    report(f"running command: {shlex.join(command)}")

    if capture_stdout:
        process = await anyio.run_process(command=command, check=False, stderr=None)
    else:
        process = await anyio.run_process(command=command, check=False, stderr=None, stdout=None)

    if process.returncode != 0:
        raise click.ClickException(error)

    if capture_stdout:
        return process.stdout.decode("utf-8")

    return None


def input_arg(name: str, value: object, cond: bool = True) -> list[str]:
    if not cond:
        return []

    assert value is not None

    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    dumped = yaml.safe_dump(value).partition("\n")[0]
    return [f"-f=inputs[{name}]={dumped}"]


@click.group("gh", help="For working with GitHub")
def gh_group() -> None:
    pass


@chia_command(
    group=gh_group,
    name="test",
    short_help="launch a test run in CI from HEAD or existing remote ref",
    help="""Allows easy triggering and viewing of test workflow runs in CI including
    configuration of parameters.  If a ref is specified then it must exist on the
    remote and a run will be launched for it.  If ref is not specified then the local
    HEAD will be pushed to a temporary remote branch and a run will be launched for
    that.  There is no need to push the local commit first.  The temporary remote
    branch will automatically be deleted in most cases.

    After launching the workflow run GitHub will be queried for the run and the URL
    will be opened in the default browser.
    """,
)
class TestCMD:
    workflow_id: ClassVar[str] = "test.yml"
    owner: str = option("-o", "--owner", help="Owner of the repo", type=str, default="Chia-Network")
    repository: str = option("-r", "--repository", help="Repository name", type=str, default="chia-blockchain")
    ref: Optional[str] = option(
        "-f",
        "--ref",
        help="Branch or tag name (commit SHA not supported), if not specified will push HEAD to a temporary branch",
        type=str,
        default=None,
    )
    per: Per = option("-p", "--per", help="Per", type=click.Choice(["directory", "file"]), default="directory")
    only: Optional[Path] = option(
        "-o", "--only", help="Only run this item, a file or directory depending on --per", type=Path
    )
    duplicates: int = option("-d", "--duplicates", help="Number of duplicates", type=int, default=1)
    oses: Sequence[Oses] = option(
        "--os",
        help="Operating systems to run on",
        type=click.Choice(all_oses),
        multiple=True,
        default=all_oses,
    )
    full_python_matrix: bool = option(
        "--full-python-matrix/--default-python-matrix", help="Run on all Python versions", default=False
    )
    remote: str = option("-r", "--remote", help="Name of git remote", type=str, default="origin")
    open_browser: bool = option("--open-browser/--no-open-browser", help="Open browser", default=True)

    async def run(self) -> None:
        await self.check_only()

        username = await self.get_username()

        if self.ref is not None:
            await self.trigger_workflow(self.ref)
            query = "+".join(
                [
                    "event=workflow_dispatch",
                    f"branch={self.ref}",
                    f"actor={username}",
                ]
            )
            run_url = f"https://github.com/Chia-Network/chia-blockchain/actions/workflows/test.yml?query={urllib.parse.quote(query)}"
            report(f"waiting a few seconds to load: {run_url}")
            await anyio.sleep(10)
        else:
            process = await anyio.run_process(command=["git", "rev-parse", "HEAD"], check=True, stderr=None)
            if process.returncode != 0:
                raise click.ClickException("Failed to get current commit SHA")

            commit_sha = process.stdout.decode("utf-8").strip()

            temp_branch_name = f"tmp/{username}/{commit_sha}/{uuid.uuid4()}"

            process = await anyio.run_process(
                command=["git", "push", self.remote, f"HEAD:{temp_branch_name}"], check=False, stdout=None, stderr=None
            )
            if process.returncode != 0:
                raise click.ClickException("Failed to push temporary branch")

            try:
                await self.trigger_workflow(temp_branch_name)
                for _ in range(10):
                    await anyio.sleep(1)

                    try:
                        report("looking for run")
                        html_url, api_url = await self.find_run(temp_branch_name)
                        report(f"run found at: {html_url}")
                        report(f"run found at: {api_url}")
                    except UnexpectedFormError:
                        report("run not found")
                        continue

                    break
                else:
                    raise click.ClickException("Failed to find run url")
            finally:
                report(f"deleting temporary branch: {temp_branch_name}")
                process = await anyio.run_process(
                    command=["git", "push", self.remote, "-d", temp_branch_name], check=False, stdout=None, stderr=None
                )
                if process.returncode != 0:
                    raise click.ClickException("Failed to dispatch workflow")
                report(f"temporary branch deleted: {temp_branch_name}")

        report(f"run html url: {html_url}")
        report(f"run api url: {api_url}")
        if self.open_browser:
            webbrowser.open(html_url)

    async def check_only(self) -> None:
        if self.only is not None:
            import chia._tests

            test_path = Path(chia._tests.__file__).parent
            effective_path = test_path.joinpath(self.only)
            checks: dict[Per, Callable[[], bool]] = {"directory": effective_path.is_dir, "file": effective_path.is_file}
            check = checks[self.per]
            if not check():
                if effective_path.exists():
                    explanation = "wrong type"
                else:
                    explanation = "does not exist"
                message = f"expected requested --only to be a {self.per}, {explanation} at: {effective_path.as_posix()}"
                raise click.ClickException(message)

    async def trigger_workflow(self, ref: str) -> None:
        # https://docs.github.com/en/rest/actions/workflows?apiVersion=2022-11-28#create-a-workflow-dispatch-event
        await run_gh_api(
            method="POST",
            args=[
                f"/repos/{self.owner}/{self.repository}/actions/workflows/{self.workflow_id}/dispatches",
                f"-f=ref={ref}",
                *input_arg("per", self.per),
                *input_arg("only", self.only, self.only is not None),
                *input_arg("duplicates", self.duplicates),
                *(arg for os_name in all_oses for arg in input_arg(f"run-{os_name}", os_name in self.oses)),
                *input_arg("full-python-matrix", self.full_python_matrix),
            ],
            error="Failed to dispatch workflow",
        )
        report(f"workflow triggered on branch: {ref}")

    async def find_run(self, ref: str) -> tuple[str, str]:
        # https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2022-11-28#list-workflow-runs-for-a-workflow
        stdout = await run_gh_api(
            method="GET",
            args=[
                f"-f=branch={ref}",
                f"/repos/{self.owner}/{self.repository}/actions/workflows/{self.workflow_id}/runs",
            ],
            error="Failed to query workflow runs",
            capture_stdout=True,
        )

        response = json.loads(stdout)
        runs = response["workflow_runs"]
        try:
            [run] = runs
        except ValueError:
            raise UnexpectedFormError(f"expected 1 run, got: {len(runs)}")

        html_url = run["html_url"]
        assert isinstance(html_url, str), f"expected html url to be a string, got: {html_url!r}"

        api_url = run["url"]
        assert isinstance(api_url, str), f"expected url to be a string, got: {api_url!r}"

        return html_url, api_url

    async def get_username(self) -> str:
        # https://docs.github.com/en/rest/users/users?apiVersion=2022-11-28#get-the-authenticated-user
        stdout = await run_gh_api(
            method="GET",
            args=["/user"],
            error="Failed to get username",
            capture_stdout=True,
        )

        response = json.loads(stdout)
        username = response["login"]
        assert isinstance(username, str), f"expected username to be a string, got: {username!r}"
        return username
