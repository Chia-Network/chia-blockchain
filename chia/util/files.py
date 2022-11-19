from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Union

from aiofiles import tempfile
from typing_extensions import Literal

log = logging.getLogger(__name__)


def move_file(src: Path, dst: Path):
    """
    Attempts to move the file at src to dst, falling back to a copy if the move fails.
    """

    dir_perms: int = 0o700
    # Create the parent directory if necessary
    os.makedirs(dst.parent, mode=dir_perms, exist_ok=True)

    try:
        # Attempt an atomic move first
        os.replace(os.fspath(src), os.fspath(dst))
    except Exception as e:
        log.debug(f"Failed to move {src} to {dst} using os.replace, reattempting with shutil.move: {e}")
        try:
            # If that fails, use the more robust shutil.move(), though it may internally initiate a copy
            shutil.move(os.fspath(src), os.fspath(dst))
        except Exception:
            log.exception(f"Failed to move {src} to {dst} using shutil.move")
            raise


async def move_file_async(src: Path, dst: Path, *, reattempts: int = 6, reattempt_delay: float = 0.5):
    """
    Attempts to move the file at src to dst, making multiple attempts if the move fails.
    """

    remaining_attempts: int = reattempts
    while True:
        try:
            move_file(src, dst)
        except Exception:
            if remaining_attempts > 0:
                log.debug(f"Failed to move {src} to {dst}, retrying in {reattempt_delay} seconds")
                remaining_attempts -= 1
                await asyncio.sleep(reattempt_delay)
            else:
                break
        else:
            break

    if not dst.exists():
        raise FileNotFoundError(f"Failed to move {src} to {dst}")
    else:
        log.debug(f"Moved {src} to {dst}")


async def write_file_async(file_path: Path, data: Union[str, bytes], *, file_mode: int = 0o600, dir_mode: int = 0o700):
    """
    Writes the provided data to a temporary file and then moves it to the final destination.
    """

    # Create the parent directory if necessary
    os.makedirs(file_path.parent, mode=dir_mode, exist_ok=True)

    mode: Literal["w+", "w+b"] = "w+" if type(data) == str else "w+b"
    temp_file_path: Path
    async with tempfile.NamedTemporaryFile(dir=file_path.parent, mode=mode, delete=False) as f:
        temp_file_path = f.name
        await f.write(data)
        await f.flush()
        os.fsync(f.fileno())

    try:
        await move_file_async(temp_file_path, file_path)
    except Exception:
        log.exception(f"Failed to move temp file {temp_file_path} to {file_path}")
    else:
        os.chmod(file_path, file_mode)
    finally:
        # We expect the file replace/move to have succeeded, but cleanup the temp file just in case
        try:
            if Path(temp_file_path).exists():
                os.remove(temp_file_path)
        except Exception:
            log.exception(f"Failed to remove temp file {temp_file_path}")
