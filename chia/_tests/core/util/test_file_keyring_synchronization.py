from __future__ import annotations

import logging
import os
import time
from multiprocessing import Pool
from pathlib import Path
from sys import platform
from time import sleep

from chia._tests.core.util.test_lockfile import wait_for_enough_files_in_directory
from chia.simulator.keyring import TempKeyring
from chia.util.file_keyring import Key
from chia.util.keyring_wrapper import KeyringWrapper
from chia.util.timing import adjusted_timeout

log = logging.getLogger(__name__)


DUMMY_SLEEP_VALUE = 2


def dummy_set_passphrase(service, user, passphrase, keyring_path, index):
    with TempKeyring(existing_keyring_path=keyring_path, delete_on_cleanup=False):
        if platform == "linux" or platform == "win32" or platform == "cygwin":
            # FileKeyring's setup_keyring_file_watcher needs to be called explicitly here,
            # otherwise file events won't be detected in the child process
            KeyringWrapper.get_shared_instance().keyring.setup_keyring_file_watcher()

        # Write out a file indicating this process is ready to begin
        ready_file_path: Path = Path(keyring_path).parent / "ready" / f"{index}.ready"
        with open(ready_file_path, "w") as f:
            f.write(f"{os.getpid()}\n")

        # Wait up to 120 seconds for all processes to indicate readiness
        start_file_path: Path = Path(ready_file_path.parent) / "start"
        end = time.monotonic() + 120
        started = False
        while not started and time.monotonic() < end:
            started = start_file_path.exists()
            sleep(0.1)
        assert started

        KeyringWrapper.get_shared_instance().keyring.set_key(service=service, user=user, key=passphrase)

        found_passphrase = KeyringWrapper.get_shared_instance().keyring.get_key(service, user)
        if found_passphrase != passphrase:
            log.error(
                f"[pid:{os.getpid()}] error: didn't get expected passphrase: "
                f"get_passphrase: {found_passphrase}"  # lgtm [py/clear-text-logging-sensitive-data]
                f", expected: {passphrase}"  # lgtm [py/clear-text-logging-sensitive-data]
            )

        # Write out a file indicating this process has completed its work
        finished_file_path: Path = Path(keyring_path).parent / "finished" / f"{index}.finished"
        with open(finished_file_path, "w") as f:
            f.write(f"{os.getpid()}\n")

        assert found_passphrase == passphrase


class TestFileKeyringSynchronization:
    # When: using a new empty keyring
    def test_multiple_writers(self, empty_temp_file_keyring: TempKeyring):
        num_workers = 10
        keyring_path = str(KeyringWrapper.get_shared_instance().keyring.keyring_path)
        passphrase_list = [
            ("test-service", f"test-user-{index}", Key(f"passphrase {index}".encode()), keyring_path, index)
            for index in range(num_workers)
        ]

        # Create a directory for each process to indicate readiness
        ready_dir: Path = Path(keyring_path).parent / "ready"
        ready_dir.mkdir(parents=True, exist_ok=True)

        finished_dir: Path = Path(keyring_path).parent / "finished"
        finished_dir.mkdir(parents=True, exist_ok=True)

        # When: spinning off children to each set a passphrase concurrently
        with Pool(processes=num_workers) as pool:
            res = pool.starmap_async(dummy_set_passphrase, passphrase_list)

            assert wait_for_enough_files_in_directory(ready_dir, num_workers)

            log.warning(f"Test setup complete: {num_workers} workers ready")

            # Signal that testing should begin
            start_file_path: Path = ready_dir / "start"
            with open(start_file_path, "w") as f:
                f.write(f"{os.getpid()}\n")

            assert wait_for_enough_files_in_directory(finished_dir, num_workers)

            log.warning(f"Finished: {num_workers} workers finished")

            # Collect results
            res.get(
                timeout=adjusted_timeout(timeout=10)
            )  # 10 second timeout to prevent a bad test from spoiling the fun

        # Expect: parent process should be able to find all passphrases that were set by the child processes
        for item in passphrase_list:
            expected_passphrase = item[2]
            actual_passphrase = KeyringWrapper.get_shared_instance().keyring.get_key(service=item[0], user=item[1])
            assert expected_passphrase == actual_passphrase
