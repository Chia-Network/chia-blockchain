from pathlib import Path

from databases import Database
import tempfile
import logging
log = logging.getLogger(__name__)

"""
    This module's purpose is to replace the use of in memory databases (which encode.io/databases does not full support yet)
    It was created using temp file logic extracted from tests/core/util/db_connection.py
"""

class TempFileDatabase:
    def __init__(self):
        self.db_path = Path(tempfile.NamedTemporaryFile().name)
        if self.db_path.exists():
            self.db_path.unlink()
        self.connection = Database("sqlite:///{}".format(str(self.db_path)), timeout=5)
    
    async def disconnect(self):
        await self.connection.disconnect()
        self.db_path.unlink()