import fasteners
import logging
import os
import pytest
import random
import sys
import unittest

from multiprocessing import Pool, Process, Value, Array, TimeoutError
from pathlib import Path
from tests.core.util.test_keyring_wrapper import using_temp_file_keyring
from time import sleep, time

from chia.util.file_keyring import acquire_writer_lock, lockfile_path_for_file_path, FileKeyring, FileKeyringLockTimeout
from chia.util.keyring_wrapper import KeyringWrapper

log = logging.getLogger(__name__)


DUMMY_SLEEP_VALUE = 1


def dummy_set_password(service, user, password):
    # FileKeyring's setup_keyring_file_watcher needs to be called explicitly here,
    # otherwise file events won't be detected in the child process
    KeyringWrapper.get_shared_instance().keyring.setup_keyring_file_watcher()

    log.warning(f"[pid:{os.getpid()}] received: {service}, {user}, {password}, keyring location: {KeyringWrapper.get_shared_instance().keyring.keyring_path}")
    KeyringWrapper.get_shared_instance().set_password(service=service, user=user, password_bytes=password)

    # Wait a short while between writing and reading. Without proper locking, this helps ensure
    # the concurrent processes get into a bad state
    sleep(random.random() * 10 % 3)

    assert KeyringWrapper.get_shared_instance().get_password(service, user) == password


def dummy_fn_requiring_writer_lock(*args, **kwargs):
    return "A winner is you!"


def dummy_sleep_fn(*args, **kwargs):
    log.warning("in dummy_sleep_fn")
    sleep(DUMMY_SLEEP_VALUE)
    return "I'm awake!"


def dummy_abort_fn(*args, **kwargs):
    log.warning(f"[pid:{os.getpid()}] dummy_abort_fn: aborting on purpose. Lock should be released...")
    sleep(0.25)
    os.abort()


def child_writer_dispatch(func, lock_path: Path, timeout: int, max_iters: int):
    try:
        with acquire_writer_lock(lock_path, timeout, max_iters):
            result = func()
            return result
    except FileKeyringLockTimeout as e:
        log.warning(f"[pid:{os.getpid()}] caught exception in child_writer_dispatch: FileKeyringLockTimeout {e}")
        raise e
    except Exception as e:
        log.warning(f"[pid:{os.getpid()}] caught exception in child_writer_dispatch: type: {type(e)}, {e}")
        raise e


class TestFileKeyringSynchronization(unittest.TestCase):


    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_multiple_writers(self):
        num_workers = 10
        password_list = list(map(lambda x: ("test-service", f"test-user-{x}", f"password {x}"), range(num_workers)))

        # When: spinning off children to each set a password concurrently
        with Pool(processes=num_workers) as pool:
            res = pool.starmap_async(dummy_set_password, password_list)
            res.get(timeout=10)  # 10 second timeout to prevent a bad test from spoiling the fun

        # Expect: parent process should be able to find all passwords that were set by the child processes
        for item in password_list:
            expected_password = item[2]
            actual_password = KeyringWrapper.get_shared_instance().get_password(service=item[0], user=item[1])
            assert expected_password == actual_password


    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_writer_lock_timeout(self):
        """
        If a writer lock is already held, another process should not be able to acquire
        the same lock, failing after n attempts
        """
        lock_path = lockfile_path_for_file_path(KeyringWrapper.get_shared_instance().keyring.keyring_path)
        lock = fasteners.InterProcessReaderWriterLock(str(lock_path))

        # When: a writer lock is already acquired
        lock.acquire_write_lock()
        
        child_proc_fn = dummy_fn_requiring_writer_lock
        timeout = 0.25
        attempts = 4

        with Pool(processes=1) as pool:
            # When: a child process attempts to acquire the same writer lock, failing after 1 second
            res = pool.starmap_async(child_writer_dispatch, [(child_proc_fn, lock_path, timeout, attempts)])

            # Expect: the child to fail acquiring the writer lock (raises as FileKeyringLockTimeout)
            with pytest.raises(FileKeyringLockTimeout):
                result = res.get(timeout=10)  # 10 second timeout to prevent a bad test from spoiling the fun (raises as TimeoutException)

        lock.release_write_lock()


    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_writer_lock_succeeds(self):
        """
        If a write lock is already held, another process will be able to acquire the
        same lock once the lock is released by the current holder
        """
        lock_path = lockfile_path_for_file_path(KeyringWrapper.get_shared_instance().keyring.keyring_path)
        lock = fasteners.InterProcessReaderWriterLock(str(lock_path))

        # When: a writer lock is already acquired
        lock.acquire_write_lock()

        child_proc_fn = dummy_fn_requiring_writer_lock
        timeout = 0.25
        attempts = 4

        with Pool(processes=1) as pool:
            # When: a child process attempts to acquire the same writer lock, failing after 1 second
            res = pool.starmap_async(child_writer_dispatch, [(child_proc_fn, lock_path, timeout, attempts)])

            # Brief delay to allow the child to timeout once
            sleep(0.25)

            # When: the writer lock is released
            lock.release_write_lock()

            # Expect: the child to acquire the writer lock
            result = res.get(timeout=10)  # 10 second timeout to prevent a bad test from spoiling the fun
            assert result[0] == "A winner is you!"


    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_writer_lock_reacquisition_failure(self):
        """
        After the child process acquires the writer lock (and sleeps), the previous
        holder should not be able to quickly reacquire the lock
        """
        lock_path = lockfile_path_for_file_path(KeyringWrapper.get_shared_instance().keyring.keyring_path)
        lock = fasteners.InterProcessReaderWriterLock(str(lock_path))

        # When: a writer lock is already acquired
        lock.acquire_write_lock()

        child_proc_function = dummy_sleep_fn  # Sleeps for DUMMY_SLEEP_VALUE seconds
        timeout = 0.25
        attempts = 4

        with Pool(processes=1) as pool:
            # When: a child process attempts to acquire the same writer lock, failing after 1 second
            res = pool.starmap_async(child_writer_dispatch, [(child_proc_function, lock_path, timeout, attempts)])

            # When: the writer lock is released
            lock.release_write_lock()

            # Brief delay to allow the child to acquire the lock
            sleep(0.25)

            # Expect: Reacquiring the lock should fail due to the child holding the lock and sleeping
            assert lock.acquire_write_lock(timeout=0.25) is False


    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_writer_lock_reacquisition_success(self):
        """
        After the child process releases the writer lock, we should be able to
        acquire the lock
        """
        lock_path = lockfile_path_for_file_path(KeyringWrapper.get_shared_instance().keyring.keyring_path)
        lock = fasteners.InterProcessReaderWriterLock(str(lock_path))

        # When: a writer lock is already acquired
        lock.acquire_write_lock()

        child_proc_function = dummy_sleep_fn  # Sleeps for DUMMY_SLEEP_VALUE seconds
        timeout = 0.25
        attempts = 4

        with Pool(processes=1) as pool:
            # When: a child process attempts to acquire the same writer lock, failing after 1 second
            res = pool.starmap_async(child_writer_dispatch, [(child_proc_function, lock_path, timeout, attempts)])

            # When: the writer lock is released
            lock.release_write_lock()

            # Expect: Reacquiring the lock should succeed after the child finishes and releases the lock
            assert lock.acquire_write_lock(timeout=(DUMMY_SLEEP_VALUE + 0.25)) is True


    # When: using a new empty keyring
    @using_temp_file_keyring()
    def test_writer_lock_released_on_abort(self):
        """
        When a child process is holding the lock and aborts/crashes, we should be
        able to acquire the lock
        """
        lock_path = lockfile_path_for_file_path(KeyringWrapper.get_shared_instance().keyring.keyring_path)
        lock = fasteners.InterProcessReaderWriterLock(str(lock_path))

        # When: a writer lock is already acquired
        lock.acquire_write_lock()

        child_proc_function = dummy_abort_fn
        timeout = 0.25
        attempts = 4

        with Pool(processes=1) as pool:
            # When: a child process attempts to acquire the same writer lock, failing after 1 second
            res = pool.starmap_async(child_writer_dispatch, [(child_proc_function, lock_path, timeout, attempts)])

            # When: the writer lock is released
            lock.release_write_lock()
            
            # When: timing out waiting for the child process (because it aborted)
            with pytest.raises(TimeoutError):
                res.get(timeout=1)
            
            # Expect: Reacquiring the lock should succeed after the child exits, automatically releasing the lock
            assert lock.acquire_write_lock(timeout=(1)) is True
