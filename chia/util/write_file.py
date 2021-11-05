import aiofiles
import asyncio
import logging
import os
import shutil

from pathlib import Path
from typing import Union


log = logging.getLogger(__name__)


async def move_file(src: Path, dst: Path, *, reattempts: int = 6, reattempt_delay: int = 0.5):
    """
    Attempts to move the file at src to dst, falling back to a copy if the move fails.
    """

    for remaining_attempts in range(reattempts, -1, -1):
        try:
            os.replace(os.fspath(src), os.fspath(dst))
        except PermissionError:
            try:
                shutil.move(os.fspath(src), os.fspath(dst))
            except Exception:
                log.exception(f"Failed to move {src} to {dst} using shutil.move")
        except Exception:
            log.exception(f"Failed to move {src} to {dst} using os.replace")

        if not dst.exists() and remaining_attempts > 0:
            log.error(f"Failed to move {src} to {dst}, retrying in {reattempt_delay} seconds")
            await asyncio.sleep(reattempt_delay)
        else:
            break

    if not dst.exists():
        raise FileNotFoundError(f"Failed to move {src} to {dst}")
    else:
        log.debug(f"Moved {src} to {dst}")


async def write_file_async(file_path: Path, data: Union[str, bytes], *, file_mode: int = 0o600):
    """
    Writes the provided data to a temporary file and then moves it to the final destination.
    """

    dir_perms: int = 0o700
    # Create the parent directory if necessary
    os.makedirs(os.path.dirname(file_path), mode=dir_perms, exist_ok=True)

    mode: str = "w+" if type(data) == str else "w+b"
    temp_file_path: Path
    async with aiofiles.tempfile.NamedTemporaryFile(dir=file_path.parent, mode=mode, delete=False) as f:
        temp_file_path = f.name
        await f.write(data)

    try:
        await move_file(temp_file_path, file_path)
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

