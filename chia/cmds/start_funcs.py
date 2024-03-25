from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

from chia.cmds.passphrase_funcs import get_current_passphrase
from chia.daemon.client import DaemonProxy, connect_to_daemon_and_validate
from chia.util.errors import KeychainMaxUnlockAttempts
from chia.util.keychain import Keychain
from chia.util.service_groups import services_for_groups


def launch_start_daemon(root_path: Path) -> subprocess.Popen:
    os.environ["CHIA_ROOT"] = str(root_path)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

    process = subprocess.Popen(
        [sys.argv[0], "run_daemon", "--wait-for-unlock"],
        encoding="utf-8",
        stdout=subprocess.PIPE,
        creationflags=creationflags,
    )

    return process


async def create_start_daemon_connection(root_path: Path, config: Dict[str, Any]) -> Optional[DaemonProxy]:
    connection = await connect_to_daemon_and_validate(root_path, config)
    if connection is None:
        print("Starting daemon")
        # launch a daemon
        process = launch_start_daemon(root_path)
        # give the daemon a chance to start up
        if process.stdout:
            process.stdout.readline()
        await asyncio.sleep(1)
        # it prints "daemon: listening"
        connection = await connect_to_daemon_and_validate(root_path, config)
    if connection:
        passphrase = None
        if await connection.is_keyring_locked():
            passphrase = Keychain.get_cached_master_passphrase()
            if passphrase is None or not Keychain.master_passphrase_is_valid(passphrase):
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="get_current_passphrase") as executor:
                    passphrase = await asyncio.get_running_loop().run_in_executor(executor, get_current_passphrase)

        if passphrase:
            print("Unlocking daemon keyring")
            await connection.unlock_keyring(passphrase)

        return connection
    return None


async def async_start(root_path: Path, config: Dict[str, Any], group: tuple[str, ...], restart: bool) -> None:
    try:
        daemon = await create_start_daemon_connection(root_path, config)
    except KeychainMaxUnlockAttempts:
        print("Failed to unlock keyring")
        return None

    if daemon is None:
        print("Failed to create the chia daemon")
        return None

    for service in services_for_groups(group):
        if await daemon.is_running(service_name=service):
            print(f"{service}: ", end="", flush=True)
            if restart:
                if await daemon.stop_service(service_name=service):
                    print("stopped")
                else:
                    print("stop failed")
            else:
                print("Already running, use `-r` to restart")
                continue
        print(f"{service}: ", end="", flush=True)
        msg = await daemon.start_service(service_name=service)
        success = msg and msg["data"]["success"]

        if success is True:
            print("started")
        else:
            error = "no response"
            if msg:
                error = msg["data"]["error"]
            print(f"{service} failed to start. Error: {error}")
    await daemon.close()
