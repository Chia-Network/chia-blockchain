from __future__ import annotations

import asyncio
import dataclasses
import datetime
import os
import sysconfig
from dataclasses import field
from pathlib import Path
from typing import Any, Optional

import click
from chia_rs.sized_bytes import bytes32

from chia.cmds.cmd_classes import ChiaCliContext, chia_command, option
from chia.util.config import load_config


class NonZeroReturnCodeError(Exception):
    def __init__(self, returncode: int):
        super().__init__(f"Process returned non-zero exit code: {returncode}")
        self.returncode = returncode


@dataclasses.dataclass
class RunResult:
    process: asyncio.subprocess.Process
    stdout: Optional[str]
    stderr: Optional[str]


@click.group("data", help="For working with DataLayer")
def data_group() -> None:
    pass


def print_date(*args: Any, **kwargs: Any) -> None:
    s = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    print(f"{s}:", *args, **kwargs)


@chia_command(
    group=data_group,
    name="sync-time",
    # TODO: fill this out
    short_help="",
    # TODO: fill this out
    help="",
)
class SyncTimeCommand:
    # TODO: NeedsWalletRPC-alike
    context: ChiaCliContext = field(default_factory=ChiaCliContext)
    generation_limit: int = option("--generation-limit", required=True)
    store_id: bytes32 = option("--store-id", required=True)
    profile_tasks: bool = option("--profile-tasks/--no-profile-tasks")
    restart_all: bool = option("--restart-all/--no-restart-all")
    delete_db: bool = option("--delete-db/--no-delete-db")

    async def run(self) -> None:
        if self.restart_all or self.delete_db:
            await self.run_chia("stop", "-d", "all", check=False)

        if self.delete_db:
            config = load_config(
                root_path=self.context.root_path,
                filename="config.yaml",
                sub_config="data_layer",
                fill_missing_services=True,
            )
            db_path = self.context.root_path.joinpath(
                config["database_path"].replace("CHALLENGE", config["selected_network"])
            )
            print_date(f"deleting db: {db_path}")
            db_path.unlink(missing_ok=True)

        await self.run_chia("start", "wallet")
        await self.run_chia("keys", "generate", "--label", "for_testing")
        await self.wait_for_wallet_synced()
        await self.run_chia("wallet", "show")

        await self.run_chia("start", "data")

        with self.context.root_path.joinpath("log", "debug.log").open("r", encoding="utf-8") as log_file:
            log_file.seek(0, os.SEEK_END)

            while True:
                try:
                    await self.run_chia(
                        "data",
                        "subscribe",
                        "--id",
                        self.store_id.hex(),
                    )
                except NonZeroReturnCodeError:
                    print("datalayer not running yet")
                    await asyncio.sleep(1)
                    continue

                break

            await self.wait_for_wallet_synced()
            await self.run_chia("wallet", "show")

            print_date("subscribed")

            while True:
                run_result = await self.run_chia(
                    "data", "get_sync_status", "--id", self.store_id.hex(), stdout=asyncio.subprocess.PIPE
                )
                assert run_result.stdout is not None, "must not be none due to piping it in the exec call"
                if "Traceback" in run_result.stdout:
                    print_date("not syncing yet")
                    await asyncio.sleep(1)
                    continue

                break

            while True:
                print_date("checking data sync status")
                try:
                    await self.run_chia("data", "get_sync_status", "--id", self.store_id.hex())
                except NonZeroReturnCodeError:
                    break

                await asyncio.sleep(1)

            for line in log_file:
                if "terminating for timing test" in line:
                    print_date(line)
                    break

        await self.run_chia("stop", "-d", "all", check=False)

    async def wait_for_wallet_synced(self) -> None:
        print_date("waiting for wallet to sync")
        while True:
            run_result = await self.run_chia(
                "wallet",
                "show",
                stdout=asyncio.subprocess.PIPE,
            )
            assert run_result.stdout is not None, "must not be none due to piping it in the exec call"
            if "Sync status: Synced" not in run_result.stdout:
                await asyncio.sleep(1)
                continue

            print_date("wallet synced")
            break

    async def run_chia(self, *args: str, check: bool = True, **kwargs: Any) -> RunResult:
        env = os.environ.copy()
        venv_path = Path(sysconfig.get_path("scripts"))
        env["PATH"] = os.pathsep.join([os.fspath(venv_path), env["PATH"]])
        env["CHIA_DATA_LAYER_STOP_AFTER_GENERATION"] = str(self.generation_limit)
        env["CHIA_ROOT"] = os.fspath(self.context.root_path)
        env["CHIA_KEYS_ROOT"] = os.fspath(self.context.keys_root_path)

        process = await asyncio.create_subprocess_exec(
            # sys.executable,
            # "-m",
            "chia",
            *args,
            **kwargs,
            env=env,
        )
        stdout_bytes, stderr_bytes = await process.communicate()
        if stdout_bytes is None:
            stdout = None
        else:
            stdout = stdout_bytes.decode("utf-8")
        if stderr_bytes is None:
            stderr = None
        else:
            stderr = stderr_bytes.decode("utf-8")
        if check:
            assert process.returncode is not None, "must not be none due to .communicate() called above"
            if process.returncode != 0:
                raise NonZeroReturnCodeError(process.returncode)

        return RunResult(process=process, stdout=stdout, stderr=stderr)
