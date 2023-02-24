from __future__ import annotations

import logging
import os
import time
from multiprocessing import Pool, TimeoutError
from pathlib import Path
from sys import platform
from time import sleep
from typing import Any, Callable

import pytest

from chia.util.lock import Lockfile, LockfileError

log = logging.getLogger(__name__)


DUMMY_SLEEP_VALUE = 2


def dummy_fn_requiring_lock(*args: object, **kwargs: object) -> str:
    return "A winner is you!"


def dummy_sleep_fn(*args: object, **kwargs: object) -> str:
    sleep(DUMMY_SLEEP_VALUE)
    return "I'm awake!"


def dummy_abort_fn(*args: object, **kwargs: object) -> None:
    sleep(0.25)
    os.abort()


def child_writer_dispatch(func: Callable[..., Any], path: Path, timeout: int, attempts: int) -> Any:
    while attempts > 0:
        attempts -= 1
        try:
            with Lockfile.create(path, timeout):
                result = func()
                return result
        except LockfileError as e:
            log.warning(f"[pid:{os.getpid()}] caught exception in child_writer_dispatch: LockfileError {e}")
            raise e
        except Exception as e:
            log.warning(f"[pid:{os.getpid()}] caught exception in child_writer_dispatch: type: {type(e)}, {e}")
            raise e


def child_writer_dispatch_with_readiness_check(
    func: Callable[..., Any], path: Path, timeout: int, attempts: int, ready_dir: Path, finished_dir: Path
) -> Any:
    # Write out a file indicating this process is ready to begin
    ready_file_path: Path = ready_dir / f"{os.getpid()}.ready"
    with open(ready_file_path, "w") as f:
        f.write(f"{os.getpid()}\n")

    # Wait for all processes to indicate readiness
    start_file_path: Path = ready_dir / "start"
    end = time.monotonic() + 120
    started = False
    while not started and time.monotonic() < end:
        started = start_file_path.exists()
        sleep(0.1)
    assert started

    try:
        while attempts > 0:
            log.warning(f"{path}, attempts {attempts}")
            try:
                with Lockfile.create(path, timeout):
                    result = func()
                    return result
            except LockfileError:
                attempts -= 1
                if attempts == 0:
                    raise LockfileError()
            except Exception as e:
                log.warning(
                    f"[pid:{os.getpid()}] caught exception in child_writer_dispatch_with_readiness_check: "
                    f"type: {type(e)}, {e}"
                )
                raise e
    finally:
        # Write out a file indicating this process has completed its work
        finished_file_path: Path = finished_dir / f"{os.getpid()}.finished"
        with open(finished_file_path, "w") as f:
            f.write(f"{os.getpid()}\n")


def wait_for_enough_files_in_directory(dir: Path, expected_entries: int) -> bool:
    found_all: bool = False
    end = time.monotonic() + 120
    while time.monotonic() < end:
        entries = list(os.scandir(dir))
        if len(entries) < expected_entries:  # Expecting num_workers of dir entries
            log.warning(f"Polling not complete: {len(entries)} of {expected_entries} entries found")
            sleep(0.1)
        else:
            found_all = True
            break
    return found_all


@pytest.fixture(scope="function")
def ready_dir(tmp_path: Path) -> Path:
    ready_dir: Path = tmp_path / "ready"
    ready_dir.mkdir(parents=True, exist_ok=True)
    return ready_dir


@pytest.fixture(scope="function")
def finished_dir(tmp_path: Path) -> Path:
    finished_dir: Path = tmp_path / "finished"
    finished_dir.mkdir(parents=True, exist_ok=True)
    return finished_dir


def test_timeout(tmp_path: Path, ready_dir: Path, finished_dir: Path) -> None:
    """
    If the lock is already held, another process should not be able to acquire the same lock, failing after n attempts
    """
    with Lockfile.create(tmp_path):
        child_proc_fn = dummy_fn_requiring_lock
        timeout = 0.25
        attempts = 4
        num_workers = 1

        with Pool(processes=num_workers) as pool:
            # When: a child process attempts to acquire the same writer lock, failing after 1 second
            res = pool.starmap_async(
                child_writer_dispatch_with_readiness_check,
                [(child_proc_fn, tmp_path, timeout, attempts, ready_dir, finished_dir)],
            )

            assert wait_for_enough_files_in_directory(ready_dir, num_workers)

            log.warning(f"Test setup complete: {num_workers} workers ready")

            # Signal that testing should begin
            start_file_path: Path = ready_dir / "start"
            with open(start_file_path, "w") as f:
                f.write(f"{os.getpid()}\n")

            assert wait_for_enough_files_in_directory(finished_dir, num_workers)

            log.warning(f"Finished: {num_workers} workers finished")

            # Expect: the child to fail acquiring the writer lock (raises as LockfileError)
            with pytest.raises(LockfileError):
                # 10 second timeout to prevent a bad test from spoiling the fun (raises as LockfileError)
                res.get(timeout=10)


def test_succeeds(tmp_path: Path, ready_dir: Path, finished_dir: Path) -> None:
    """
    If the lock is already held, another process will be able to acquire the same lock once the lock is released by
    the current holder
    """
    # When: a lock is already acquired
    with Lockfile.create(tmp_path) as lock:
        child_proc_fn = dummy_fn_requiring_lock
        timeout = 0.25
        attempts = 8
        num_workers = 1

        with Pool(processes=num_workers) as pool:
            # When: a child process attempts to acquire the same writer lock, failing after 1 second
            res = pool.starmap_async(
                child_writer_dispatch_with_readiness_check,
                [(child_proc_fn, tmp_path, timeout, attempts, ready_dir, finished_dir)],
            )

            assert wait_for_enough_files_in_directory(ready_dir, num_workers)

            log.warning(f"Test setup complete: {num_workers} workers ready")

            # Signal that testing should begin
            start_file_path: Path = ready_dir / "start"
            with open(start_file_path, "w") as f:
                f.write(f"{os.getpid()}\n")

            # Brief delay to allow the child to timeout once
            sleep(0.50)

            # When: the writer lock is released
            lock.release()
            # Expect: the child to acquire the writer lock
            result = res.get(timeout=10)  # 10 second timeout to prevent a bad test from spoiling the fun
            assert result[0] == "A winner is you!"

            assert wait_for_enough_files_in_directory(finished_dir, num_workers)

            log.warning(f"Finished: {num_workers} workers finished")


def test_reacquisition_failure(tmp_path: Path, ready_dir: Path, finished_dir: Path) -> None:
    """
    After the child process acquires the lock (and sleeps), the previous holder should not be able to quickly reacquire
    the lock
    """
    # When: a lock is already acquired
    with Lockfile.create(tmp_path) as lock:
        child_proc_function = dummy_sleep_fn  # Sleeps for DUMMY_SLEEP_VALUE seconds
        timeout = 0.25
        attempts = 8
        num_workers = 1

        with Pool(processes=num_workers) as pool:
            # When: a child process attempts to acquire the same writer lock, failing after 1 second
            pool.starmap_async(
                child_writer_dispatch_with_readiness_check,
                [(child_proc_function, tmp_path, timeout, attempts, ready_dir, finished_dir)],
            )

            assert wait_for_enough_files_in_directory(ready_dir, num_workers)

            log.warning(f"Test setup complete: {num_workers} workers ready")

            # Signal that testing should begin
            start_file_path: Path = ready_dir / "start"
            with open(start_file_path, "w") as f:
                f.write(f"{os.getpid()}\n")

            # When: the writer lock is released
            lock.release()
            # Brief delay to allow the child to acquire the lock
            sleep(1)

            # Expect: Reacquiring the lock should fail due to the child holding the lock and sleeping
            with pytest.raises(LockfileError):
                with Lockfile.create(tmp_path, timeout=0.25):
                    pass

            assert wait_for_enough_files_in_directory(finished_dir, num_workers)

            log.warning(f"Finished: {num_workers} workers finished")


def test_reacquisition_success(tmp_path: Path, ready_dir: Path, finished_dir: Path) -> None:
    """
    After the child process releases the lock, we should be able to acquire the lock
    """
    # When: a writer lock is already acquired
    with Lockfile.create(tmp_path) as lock:
        child_proc_function = dummy_sleep_fn  # Sleeps for DUMMY_SLEEP_VALUE seconds
        timeout = 0.25
        attempts = 4
        num_workers = 1

        with Pool(processes=num_workers) as pool:
            # When: a child process attempts to acquire the same writer lock, failing after 1 second
            pool.starmap_async(
                child_writer_dispatch_with_readiness_check,
                [(child_proc_function, tmp_path, timeout, attempts, ready_dir, finished_dir)],
            )

            assert wait_for_enough_files_in_directory(ready_dir, num_workers)

            log.warning(f"Test setup complete: {num_workers} workers ready")

            # Signal that testing should begin
            start_file_path: Path = ready_dir / "start"
            with open(start_file_path, "w") as f:
                f.write(f"{os.getpid()}\n")

            # When: the writer lock is released
            lock.release()
            assert wait_for_enough_files_in_directory(finished_dir, num_workers)

            log.warning(f"Finished: {num_workers} workers finished")

            # Expect: Reacquiring the lock should succeed after the child finishes and releases the lock
            with Lockfile.create(tmp_path, timeout=(DUMMY_SLEEP_VALUE + 0.25)):
                pass


@pytest.mark.skipif(platform == "darwin", reason="triggers the CrashReporter prompt")
def test_released_on_abort(tmp_path: Path) -> None:
    """
    When a child process is holding the lock and aborts/crashes, we should be able to acquire the lock
    """
    # When: a writer lock is already acquired
    with Lockfile.create(tmp_path) as lock:
        child_proc_function = dummy_abort_fn
        timeout = 0.25
        attempts = 4

        with Pool(processes=1) as pool:
            # When: a child process attempts to acquire the same writer lock, failing after 1 second
            res = pool.starmap_async(child_writer_dispatch, [(child_proc_function, tmp_path, timeout, attempts)])

            # When: the writer lock is released
            lock.release()
            # When: timing out waiting for the child process (because it aborted)
            with pytest.raises(TimeoutError):
                res.get(timeout=2)

        # Expect: Reacquiring the lock should succeed after the child exits, automatically releasing the lock
        with Lockfile.create(tmp_path, timeout=2):
            pass


def test_blocked_by_readers(tmp_path: Path, ready_dir: Path, finished_dir: Path) -> None:
    """
    When a lock is already held, another thread/process should not be able to acquire the lock
    """
    with Lockfile.create(tmp_path):
        child_proc_function = dummy_fn_requiring_lock
        timeout = 0.25
        attempts = 4
        num_workers = 1

        with Pool(processes=num_workers) as pool:
            # When: a child process attempts to acquire the same lock for writing, failing after 1 second
            res = pool.starmap_async(
                child_writer_dispatch_with_readiness_check,
                [(child_proc_function, tmp_path, timeout, attempts, ready_dir, finished_dir)],
            )

            assert wait_for_enough_files_in_directory(ready_dir, num_workers)

            log.warning(f"Test setup complete: {num_workers} workers ready")

            # Signal that testing should begin
            start_file_path: Path = ready_dir / "start"
            with open(start_file_path, "w") as f:
                f.write(f"{os.getpid()}\n")

            assert wait_for_enough_files_in_directory(finished_dir, num_workers)

            log.warning(f"Finished: {num_workers} workers finished")

            # Expect: lock acquisition times out (raises as LockfileError)
            with pytest.raises(LockfileError):
                res.get(timeout=30)


def test_initially_blocked_by_readers(tmp_path: Path, ready_dir: Path, finished_dir: Path) -> None:
    """
    When a lock is already held, another thread/process should not be able to acquire the lock until the process
    currently holding the lock releases it
    """
    # When: the lock is already acquired
    with Lockfile.create(tmp_path) as lock:
        child_proc_function = dummy_fn_requiring_lock
        timeout = 1
        attempts = 10
        num_workers = 1

        with Pool(processes=num_workers) as pool:
            # When: a child process attempts to acquire the same lock for writing, failing after 4 seconds
            res = pool.starmap_async(
                child_writer_dispatch_with_readiness_check,
                [(child_proc_function, tmp_path, timeout, attempts, ready_dir, finished_dir)],
            )

            assert wait_for_enough_files_in_directory(ready_dir, num_workers)

            log.warning(f"Test setup complete: {num_workers} workers ready")

            # Signal that testing should begin
            start_file_path: Path = ready_dir / "start"
            with open(start_file_path, "w") as f:
                f.write(f"{os.getpid()}\n")

            # When: we verify that the writer lock is not immediately acquired
            with pytest.raises(TimeoutError):
                res.get(timeout=5)

            # When: the reader releases its lock
            lock.release()
            assert wait_for_enough_files_in_directory(finished_dir, num_workers)

            log.warning(f"Finished: {num_workers} workers finished")

            # Expect: the child process to acquire the writer lock
            result = res.get(timeout=10)  # 10 second timeout to prevent a bad test from spoiling the fun
            assert result[0] == "A winner is you!"
