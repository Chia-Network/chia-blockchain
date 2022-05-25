import contextlib
import os
import time
from typing import Iterator, Optional, TextIO, TypeVar

T = TypeVar("T")


# Cribbed mostly from chia/daemon/server.py
def create_exclusive_lock(lockfile: str) -> Optional[TextIO]:
    """
    Open a lockfile exclusively.
    """

    try:
        fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        f = open(fd, "w")

        f.write("lock")
    except IOError:
        return None

    return f


@contextlib.contextmanager
def lock_by_path(lock_filename: str) -> Iterator[None]:
    """
    Ensure that this process and this thread is the only one operating on the
    resource associated with lock_filename systemwide.
    """

    while True:
        lock_file = create_exclusive_lock(lock_filename)
        if lock_file is not None:
            break

        time.sleep(0.1)

    try:
        yield
    finally:
        lock_file.close()
        os.remove(lock_filename)
