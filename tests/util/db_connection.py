from pathlib import Path
from chia.util.db_wrapper import DBWrapper
import tempfile
import aiosqlite


class DBConnection:
    def __init__(self, db_version):
        self.db_version = db_version

    async def __aenter__(self) -> DBWrapper:
        self.db_path = Path(tempfile.NamedTemporaryFile().name)
        if self.db_path.exists():
            self.db_path.unlink()
        self.connection = await aiosqlite.connect(self.db_path)
        return DBWrapper(self.connection, self.db_version)

    async def __aexit__(self, exc_t, exc_v, exc_tb):
        await self.connection.close()
        self.db_path.unlink()
