from pathlib import Path
from chia.util.db_wrapper import DBWrapper2
from chia.util.db_wrapper import DBWrapper
import tempfile
import aiosqlite


async def log_conn(c: aiosqlite.Connection, name: str) -> aiosqlite.Connection:
    # uncomment this to debug sqlite interactions
    # from datetime import datetime
    # import sys
    # def sql_trace_callback(req: str):
    #    timestamp = datetime.now().strftime("%H:%M:%S.%f")
    #    sys.stdout.write(timestamp + " " + name + " " + req + "\n")
    # await c.set_trace_callback(sql_trace_callback)
    return c


class DBConnection:
    def __init__(self, db_version: int) -> None:
        self.db_version = db_version

    async def __aenter__(self) -> DBWrapper2:
        self.db_path = Path(tempfile.NamedTemporaryFile().name)
        if self.db_path.exists():
            self.db_path.unlink()
        connection = await aiosqlite.connect(self.db_path)
        self._db_wrapper = DBWrapper2(await log_conn(connection, "writer"), self.db_version)

        for i in range(4):
            await self._db_wrapper.add_connection(await log_conn(await aiosqlite.connect(self.db_path), f"reader-{i}"))
        return self._db_wrapper

    async def __aexit__(self, exc_t, exc_v, exc_tb) -> None:
        await self._db_wrapper.close()
        self.db_path.unlink()


# This is just here until all DBWrappers have been upgraded to DBWrapper2
class DBConnection1:
    async def __aenter__(self) -> DBWrapper:
        self.db_path = Path(tempfile.NamedTemporaryFile().name)
        if self.db_path.exists():
            self.db_path.unlink()
        self._db_connection = await aiosqlite.connect(self.db_path)
        self._db_wrapper = DBWrapper(self._db_connection)
        return self._db_wrapper

    async def __aexit__(self, exc_t, exc_v, exc_tb) -> None:
        await self._db_connection.close()
        self.db_path.unlink()
