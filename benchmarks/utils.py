from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from chia.util.db_wrapper import DBWrapper2


@contextlib.asynccontextmanager
async def setup_db(name: str | os.PathLike[str], db_version: int) -> AsyncIterator[DBWrapper2]:
    db_filename = Path(name)
    try:
        os.unlink(db_filename)
    except FileNotFoundError:
        pass

    log_path: Path | None
    if "--sql-logging" in sys.argv:
        log_path = Path("sql.log")
    else:
        log_path = None

    async with DBWrapper2.managed(
        database=db_filename,
        log_path=log_path,
        db_version=db_version,
        reader_count=1,
        journal_mode="wal",
        synchronous="full",
    ) as db_wrapper:
        yield db_wrapper


def get_commit_hash() -> str:
    try:
        os.chdir(Path(os.path.realpath(__file__)).parent)
        commit_hash = (
            subprocess.run(["git", "rev-parse", "--short", "HEAD"], check=True, stdout=subprocess.PIPE)
            .stdout.decode("utf-8")
            .strip()
        )
    except Exception:
        sys.exit("Failed to get the commit hash")
    try:
        if len(subprocess.run(["git", "status", "-s"], check=True, stdout=subprocess.PIPE).stdout) > 0:
            raise Exception
    except Exception:
        commit_hash += "-dirty"
    return commit_hash
