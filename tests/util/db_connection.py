from pathlib import Path
from chia.util.db_wrapper import DBWrapper

from chia.util.temp_file_db import TempFileDatabase


class DBConnection:
    def __init__(self, db_version):
        self.db_version = db_version

    async def __aenter__(self) -> DBWrapper:
        self.temp_file_db = TempFileDatabase()
        self.connection = self.temp_file_db.connection
        await self.connection.connect()
        return DBWrapper(self.connection, self.db_version)

    async def __aexit__(self, exc_t, exc_v, exc_tb):
        await self.temp_file_db.disconnect()
