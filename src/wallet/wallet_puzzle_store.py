import asyncio
from typing import Set
from pathlib import Path
import aiosqlite
from src.types.sized_bytes import bytes32
from src.util.ints import uint32
from src.wallet.util.wallet_types import WalletType


class WalletPuzzleStore:
    """
    This object handles CoinRecords in DB used by wallet.
    """

    db_connection: aiosqlite.Connection
    # Whether or not we are syncing
    lock: asyncio.Lock
    cache_size: uint32

    @classmethod
    async def create(cls, db_path: Path, cache_size: uint32 = uint32(600000)):
        self = cls()

        self.cache_size = cache_size

        self.db_connection = await aiosqlite.connect(db_path)

        await self.db_connection.execute(
            (
                f"CREATE TABLE IF NOT EXISTS derivation_paths("
                f"id int PRIMARY KEY,"
                f" pubkey text,"
                f" puzzle_hash text,"
                f" wallet_type int,"
                f" used int)"
            )
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS ph on derivation_paths(puzzle_hash)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS pubkey on derivation_paths(pubkey)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS wallet_type on derivation_paths(wallet_type)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS used on derivation_paths(wallet_type)"
        )

        await self.db_connection.commit()
        # Lock
        self.lock = asyncio.Lock()  # external
        return self

    async def close(self):
        await self.db_connection.close()

    async def _init_cache(self):
        print("init cache here")

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM transaction_record")
        await cursor.close()
        await self.db_connection.commit()

    async def add_derivation_path_of_interest(
        self, index: int, puzzlehash: bytes32, pubkey: bytes, wallet_type: WalletType
    ):
        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO derivation_paths VALUES(?, ?, ?, ?, ?)",
            (index, pubkey.hex(), puzzlehash.hex(), wallet_type.value, 0),
        )

        await cursor.close()
        await self.db_connection.commit()

    async def puzzle_hash_exists(self, puzzle_hash: bytes32) -> bool:
        cursor = await self.db_connection.execute(
            "SELECT * from derivation_paths WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        rows = await cursor.fetchall()
        await cursor.close()

        if len(list(rows)) > 0:
            return True

        return False

    async def index_for_pubkey(self, pubkey: str) -> int:
        cursor = await self.db_connection.execute(
            "SELECT * from derivation_paths WHERE pubkey=?", (pubkey,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            return row[0]

        return -1

    async def index_for_puzzle_hash(self, pubkey: bytes32) -> int:
        cursor = await self.db_connection.execute(
            "SELECT * from derivation_paths WHERE puzzle_hash=?", (pubkey.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            return row[0]

        return -1

    async def get_all_puzzle_hashes(self) -> Set[bytes32]:
        """ Return a set containing all puzzle_hashes we generated. """
        cursor = await self.db_connection.execute("SELECT * from derivation_paths")
        rows = await cursor.fetchall()
        await cursor.close()
        result: Set[bytes32] = set()

        for row in rows:
            result.add(row[2])

        return result

    async def get_max_derivation_path(self):
        cursor = await self.db_connection.execute(
            "SELECT MAX(id) FROM derivation_paths;"
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row[0]:
            return row[0]

        return 0
