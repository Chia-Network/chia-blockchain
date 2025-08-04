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
from chia.data_layer.data_layer_util import ServerInfo, Status, Subscription
from chia.data_layer.data_store import DataStore
from chia.data_layer.download_data import insert_from_delta_file
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config
from chia.util.task_referencer import create_referenced_task
from chia.wallet.wallet_request_types import DLHistory, DLTrackNew


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
    kwargs.setdefault("flush", True)
    s = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    print(f"{s}:", *args, **kwargs)


def humanize_bytes(size: int) -> str:
    return f"{size / 2**20:.1f} MB"


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
    working_path: Optional[Path] = option("--working-path", default=None)

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
                working_path: Path
                if self.working_path is None:
                    working_path = Path(exit_stack.enter_context(tempfile.TemporaryDirectory()))
                else:
                    working_path = self.working_path
                    working_path.mkdir(parents=True, exist_ok=True)

                database_path = working_path.joinpath("datalayer.sqlite")
                print_date(f"working with database at: {database_path}")

                wallet_client_info = await exit_stack.enter_async_context(self.wallet_rpc_info.wallet_rpc())
                wallet_rpc = wallet_client_info.client
                await wallet_rpc.dl_track_new(DLTrackNew(launcher_id=self.store_id))

                data_store = await exit_stack.enter_async_context(DataStore.managed(database=database_path))

                await data_store.subscribe(subscription=Subscription(store_id=self.store_id, servers_info=[]))

                await self.wait_for_wallet_synced()
                await self.run_chia("wallet", "show")

                print_date("subscribed")

                to_download = (
                    await wallet_rpc.dl_history(
                        DLHistory(
                            launcher_id=self.store_id,
                            min_generation=uint32(1),
                            max_generation=uint32(self.generation_limit + 1),
                        )
                    )
                ).history

                print_date(
                    f"found generations to download: {to_download[-1].generation} -> {to_download[0].generation}"
                )

                root_hashes = [record.root for record in reversed(to_download)]

                files_path = server_files_path_from_config(config=config, root_path=self.context.root_path)

                clock = time.monotonic
                start = clock()

                last_generation = -1
                clock = time.monotonic
                last_time = clock()
                all_times: dict[int, float] = {}

                print_date(f"using local files at: {files_path}")

                await data_store.create_tree(store_id=self.store_id, status=Status.COMMITTED)

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
                        maximum_full_file_count=0,
                    )
                )
                try:
                    while not task.done():
                        try:
                            generation = await data_store.get_tree_generation(store_id=self.store_id)
                        except Exception as e:
                            if "No generations found" not in str(e):
                                raise
                        else:
                            if generation != last_generation:
                                delta_generation = generation - last_generation
                                now = clock()
                                delta_time = now - last_time
                                per_generation = delta_time / delta_generation

                                duration_so_far = round((now - start) / 60)

                                print_date(
                                    f"synced: {last_generation} -> {generation} at {per_generation:.1f}s / gen"
                                    + f" ({humanize_bytes(database_path.stat().st_size)}, {duration_so_far}m)",
                                    flush=True,
                                )

                                for i in range(generation, last_generation, -1):
                                    all_times[i] = per_generation

                                last_generation = generation
                                last_time = now
                        await asyncio.sleep(1)
                finally:
                    try:
                        with anyio.CancelScope(shield=True):
                            if task.done():
                                await task
                            else:
                                task.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await task
                    finally:
                        end = clock()
                        total = round(end - start)
                        remainder, seconds = divmod(total, 60)
                        remainder, minutes = divmod(remainder, 60)
                        days, hours = divmod(remainder, 24)
                        # TODO: report better on failure
                        print_date("DataLayer sync timing test results:")
                        print(f"    store id: {self.store_id}")
                        print(f"     reached: {generation}")
                        print(f"     db size: {humanize_bytes(database_path.stat().st_size)}")
                        print(f"    duration: {days}d {hours}h {minutes}m {seconds}s")
                        print(f"              {total}s")
                        if len(all_times) > 0:
                            generation, duration = max(all_times.items(), key=lambda item: item[1])
                            print(f"         max: {generation} @ {duration:.1f}s")
        finally:
            with anyio.CancelScope(shield=True):
                print_date("stopping services")
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
