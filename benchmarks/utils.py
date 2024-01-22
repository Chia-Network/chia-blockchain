from __future__ import annotations

import contextlib
import enum
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Generic, Optional, Type, TypeVar, Union

import click

from chia.util.db_wrapper import DBWrapper2

_T_Enum = TypeVar("_T_Enum", bound=enum.Enum)


# Workaround to allow `Enum` with click.Choice: https://github.com/pallets/click/issues/605#issuecomment-901099036
class EnumType(click.Choice, Generic[_T_Enum]):
    def __init__(self, enum: Type[_T_Enum], case_sensitive: bool = False) -> None:
        self.__enum = enum
        super().__init__(choices=[item.value for item in enum], case_sensitive=case_sensitive)

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> _T_Enum:
        converted_str = super().convert(value, param, ctx)
        return self.__enum(converted_str)


@contextlib.asynccontextmanager
async def setup_db(name: Union[str, os.PathLike[str]], db_version: int) -> AsyncIterator[DBWrapper2]:
    db_filename = Path(name)
    try:
        os.unlink(db_filename)
    except FileNotFoundError:
        pass

    log_path: Optional[Path]
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
            raise Exception()
    except Exception:
        commit_hash += "-dirty"
    return commit_hash
