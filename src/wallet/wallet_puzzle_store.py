import asyncio
from typing import Set, Tuple, Optional
from pathlib import Path
import aiosqlite
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.wallet.util.wallet_types import WalletType


class WalletPuzzleStore:
    """
    WalletPuzzleStore keeps track of all generated puzzle_hashes and their derivation path / wallet.
    """

    db_connection: aiosqlite.Connection
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
                f" wallet_id int,"
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
            "CREATE INDEX IF NOT EXISTS wallet_ud on derivation_paths(wallet_id)"
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
        # TODO create cache
        print("init cache here")

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM derivation_paths")
        await cursor.close()
        await self.db_connection.commit()

    async def add_derivation_path_of_interest(
        self,
        index: int,
        puzzlehash: bytes32,
        pubkey: bytes,
        wallet_type: WalletType,
        wallet_id: int,
    ):
        """
        Inserts new derivation path, puzzle, pubkey, wallet into DB.
        """

        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO derivation_paths VALUES(?, ?, ?, ?, ?, ?)",
            (index, pubkey.hex(), puzzlehash.hex(), wallet_type.value, wallet_id, 0),
        )

        await cursor.close()
        await self.db_connection.commit()

    async def puzzle_hash_exists(self, puzzle_hash: bytes32) -> bool:
        """
        Checks if passed puzzle_hash is present in the db.
        """

        cursor = await self.db_connection.execute(
            "SELECT * from derivation_paths WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        rows = await cursor.fetchall()
        await cursor.close()

        if len(list(rows)) > 0:
            return True

        return False

    async def index_for_pubkey(self, pubkey: str) -> int:
        """
        Returns derivation path for the given pubkey.
        Returns -1 if not present.
        """

        cursor = await self.db_connection.execute(
            "SELECT * from derivation_paths WHERE pubkey=?", (pubkey,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            return row[0]

        return -1

    async def index_for_puzzle_hash(self, puzzle_hash: bytes32) -> int:
        """
        Returns the derivation path for the puzzle_hash.
        Returns -1 if not present.
        """

        cursor = await self.db_connection.execute(
            "SELECT * from derivation_paths WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            return row[0]

        return -1

    async def wallet_info_for_puzzle_hash(
        self, puzzle_hash: bytes32
    ) -> Optional[Tuple[uint64, WalletType]]:
        """
        Returns the derivation path for the puzzle_hash.
        Returns -1 if not present.
        """

        cursor = await self.db_connection.execute(
            "SELECT * from derivation_paths WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            return row[4], WalletType(row[3])

        return None

    async def get_all_puzzle_hashes(self) -> Set[bytes32]:
        """
        Return a set containing all puzzle_hashes we generated.
        """

        cursor = await self.db_connection.execute("SELECT * from derivation_paths")
        rows = await cursor.fetchall()
        await cursor.close()
        result: Set[bytes32] = set()

        for row in rows:
            result.add(bytes32(bytes.fromhex(row[2])))

        return result

    async def get_max_derivation_path(self):
        """
        Returns the highest derivation path currently stored.
        """

        cursor = await self.db_connection.execute(
            "SELECT MAX(id) FROM derivation_paths;"
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row[0] is not None:
            return row[0]

        return -1
