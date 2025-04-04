from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import datetime
import logging
import os
import sysconfig
import tempfile
import time
from dataclasses import field
from pathlib import Path
from typing import Any, Optional

import aiohttp
import anyio
import click
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.cmds.cmd_classes import ChiaCliContext, chia_command, option
from chia.cmds.cmd_helpers import NeedsWalletRPC
from chia.data_layer.data_layer import server_files_path_from_config
from chia.data_layer.data_layer_util import ServerInfo, Subscription
from chia.data_layer.data_store import DataStore
from chia.data_layer.download_data import insert_from_delta_file
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config
from chia.util.task_referencer import create_referenced_task


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
    s = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    print(f"{s}:", *args, **kwargs)


@chia_command(
    group=data_group,
    name="sync-time",
    short_help="test time to sync a provided store id",
    help="""
        An empty temporary database is created and then the specified store is synced to it.
        If local delta files are available in the specified directory then they will be used.
        This allows both testing of total time including downloading as well as just the insert time.
        The DataLayer work is done within the test process.
        Separate daemon and wallet service processes are started and stopped.""",
)
class SyncTimeCommand:
    wallet_rpc_info: NeedsWalletRPC
    context: ChiaCliContext = field(default_factory=ChiaCliContext)
    generation_limit: int = option("--generation-limit", required=True)
    store_id: bytes32 = option("--store-id", required=True)
    profile_tasks: bool = option("--profile-tasks/--no-profile-tasks")
    restart_all: bool = option("--restart-all/--no-restart-all")

    async def run(self) -> None:
        config = load_config(self.context.root_path, "config.yaml", "data_layer", fill_missing_services=True)
        initialize_logging(
            service_name="data_layer_testing",
            logging_config=config["logging"],
            root_path=self.context.root_path,
        )

        if self.restart_all:
            await self.run_chia("stop", "-d", "all", check=False)

        await self.run_chia("start", "wallet")
        await self.run_chia("keys", "generate", "--label", "for_testing")
        await self.wait_for_wallet_synced()
        await self.run_chia("wallet", "show")

        try:
            async with contextlib.AsyncExitStack() as exit_stack:
                temp_dir = exit_stack.enter_context(tempfile.TemporaryDirectory())
                database_path = Path(temp_dir).joinpath("datalayer.sqlite")

                data_store = await exit_stack.enter_async_context(DataStore.managed(database=database_path))

                await data_store.subscribe(subscription=Subscription(store_id=self.store_id, servers_info=[]))

                await self.wait_for_wallet_synced()
                await self.run_chia("wallet", "show")

                print_date("subscribed")

                wallet_client_info = await exit_stack.enter_async_context(self.wallet_rpc_info.wallet_rpc())
                wallet_rpc = wallet_client_info.client

                to_download = await wallet_rpc.dl_history(
                    launcher_id=self.store_id,
                    min_generation=uint32(1),
                    max_generation=uint32(self.generation_limit + 1),
                )

                root_hashes = [record.root for record in reversed(to_download)]

                files_path = server_files_path_from_config(config=config, root_path=self.context.root_path)

                clock = time.monotonic
                start = clock()

                task = create_referenced_task(
                    insert_from_delta_file(
                        data_store=data_store,
                        store_id=self.store_id,
                        existing_generation=0,
                        target_generation=self.generation_limit,
                        root_hashes=root_hashes,
                        server_info=ServerInfo(url="", num_consecutive_failures=0, ignore_till=0),
                        client_foldername=files_path,
                        timeout=aiohttp.ClientTimeout(),
                        log=logging.getLogger(__name__),
                        proxy_url=None,
                        downloader=None,
                    )
                )
                last_generation = -1
                try:
                    while not task.done():
                        try:
                            generation = await data_store.get_tree_generation(store_id=self.store_id)
                        except Exception as e:
                            if "No generations found" not in str(e):
                                raise
                        else:
                            if generation != last_generation:
                                last_generation = generation
                                print_date(f"synced to: {generation}")
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    with anyio.CancelScope(shield=True):
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task

                end = clock()
                remainder = round(end - start)
                remainder, seconds = divmod(remainder, 60)
                remainder, minutes = divmod(remainder, 60)
                days, hours = divmod(remainder, 24)
                print("DataLayer sync timing test complete:")
                print(f"    store id: {self.store_id}")
                print(f"     reached: {self.generation_limit}")
                print(f"    duration: {days}d {hours}h {minutes}m {seconds}s")
        finally:
            with anyio.CancelScope(shield=True):
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
