from __future__ import annotations

import logging
import os
from multiprocessing import Pool
from pathlib import Path
from sys import platform
from time import sleep

from chia.simulator.keyring import TempKeyring, using_temp_file_keyring
from chia.simulator.time_out_assert import adjusted_timeout
from chia.util.keyring_wrapper import KeyringWrapper
from tests.core.util.test_lockfile import poll_directory

log = logging.getLogger(__name__)


DUMMY_SLEEP_VALUE = 2


def dummy_set_passphrase(service, user, passphrase, keyring_path, index, num_workers):
    with TempKeyring(existing_keyring_path=keyring_path, delete_on_cleanup=False):
        if platform == "linux" or platform == "win32" or platform == "cygwin":
            # FileKeyring's setup_keyring_file_watcher needs to be called explicitly here,
            # otherwise file events won't be detected in the child process
            KeyringWrapper.get_shared_instance().keyring.setup_keyring_file_watcher()

        # Write out a file indicating this process is ready to begin
        ready_file_path: Path = Path(keyring_path).parent / "ready" / f"{index}.ready"
        with open(ready_file_path, "w") as f:
            f.write(f"{os.getpid()}\n")

        # Wait up to 30 seconds for all processes to indicate readiness
        start_file_path: Path = Path(ready_file_path.parent) / "start"
        remaining_attempts = 120
        while remaining_attempts > 0:
            if start_file_path.exists():
                break
            else:
                sleep(0.25)
                remaining_attempts -= 1

        assert remaining_attempts >= 0

        KeyringWrapper.get_shared_instance().set_passphrase(service=service, user=user, passphrase=passphrase)

        found_passphrase = KeyringWrapper.get_shared_instance().get_passphrase(service, user)
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
    @using_temp_file_keyring()
    def test_multiple_writers(self):
        num_workers = 20
        keyring_path = str(KeyringWrapper.get_shared_instance().keyring.keyring_path)
        passphrase_list = list(
            map(
                lambda x: ("test-service", f"test-user-{x}", f"passphrase {x}", keyring_path, x, num_workers),
                range(num_workers),
            )
        )

        # Create a directory for each process to indicate readiness
        ready_dir: Path = Path(keyring_path).parent / "ready"
        ready_dir.mkdir(parents=True, exist_ok=True)

        finished_dir: Path = Path(keyring_path).parent / "finished"
        finished_dir.mkdir(parents=True, exist_ok=True)

        # When: spinning off children to each set a passphrase concurrently
        with Pool(processes=num_workers) as pool:
            res = pool.starmap_async(dummy_set_passphrase, passphrase_list)

            # Wait up to 30 seconds for all processes to indicate readiness
            assert poll_directory(ready_dir, num_workers, 30) is True

            log.warning(f"Test setup complete: {num_workers} workers ready")

            # Signal that testing should begin
            start_file_path: Path = ready_dir / "start"
            with open(start_file_path, "w") as f:
                f.write(f"{os.getpid()}\n")

            # Wait up to 30 seconds for all processes to indicate completion
            assert poll_directory(finished_dir, num_workers, 30) is True

            log.warning(f"Finished: {num_workers} workers finished")

            # Collect results
            res.get(
                timeout=adjusted_timeout(timeout=10)
            )  # 10 second timeout to prevent a bad test from spoiling the fun

        # Expect: parent process should be able to find all passphrases that were set by the child processes
        for item in passphrase_list:
            expected_passphrase = item[2]
            actual_passphrase = KeyringWrapper.get_shared_instance().get_passphrase(service=item[0], user=item[1])
            assert expected_passphrase == actual_passphrase
