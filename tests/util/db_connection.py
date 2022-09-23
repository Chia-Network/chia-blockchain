from pathlib import Path
from chia.util.db_wrapper import DBWrapper2
from chia.util.db_wrapper import DBWrapper
import tempfile
import aiosqlite


class DBConnection:
    def __init__(self, db_version: int) -> None:
        self.db_version = db_version

    async def __aenter__(self) -> DBWrapper2:
        self.db_path = Path(tempfile.NamedTemporaryFile().name)
        if self.db_path.exists():
            self.db_path.unlink()
        self._db_wrapper = await DBWrapper2.create(database=self.db_path, reader_count=4, db_version=self.db_version)

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
