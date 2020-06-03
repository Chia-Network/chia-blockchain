import asyncio
from blspy import PublicKey
from typing import Set, Tuple, Optional, List
import aiosqlite
import logging
from src.types.sized_bytes import bytes32
from src.util.ints import uint32
from src.wallet.util.wallet_types import WalletType
from src.wallet.derivation_record import DerivationRecord

log = logging.getLogger(__name__)


class WalletPuzzleStore:
    """
    WalletPuzzleStore keeps track of all generated puzzle_hashes and their derivation path / wallet.
    """

    db_connection: aiosqlite.Connection
    lock: asyncio.Lock
    cache_size: uint32

    @classmethod
    async def create(
        cls, connection: aiosqlite.Connection, cache_size: uint32 = uint32(600000)
    ):
        self = cls()

        self.cache_size = cache_size

        self.db_connection = connection

        await self.db_connection.execute(
            (
                "CREATE TABLE IF NOT EXISTS derivation_paths("
                "derivation_index int,"
                " pubkey text,"
                " puzzle_hash text PRIMARY_KEY,"
                " wallet_type int,"
                " wallet_id int,"
                " used tinyint)"
            )
        )
        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS derivation_index_index on derivation_paths(derivation_index)"
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
            "CREATE INDEX IF NOT EXISTS wallet_id on derivation_paths(wallet_id)"
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

    async def add_derivation_paths(self, records: List[DerivationRecord]) -> None:
        """
        Insert many derivation paths into the database.
        """
        sql_records = []
        for record in records:
            sql_records.append(
                (
                    record.index,
                    bytes(record.pubkey).hex(),
                    record.puzzle_hash.hex(),
                    record.wallet_type.value,
                    record.wallet_id,
                    0,
                ),
            )

        cursor = await self.db_connection.executemany(
            "INSERT OR REPLACE INTO derivation_paths VALUES(?, ?, ?, ?, ?, ?)",
            sql_records,
        )

        await cursor.close()
        await self.db_connection.commit()

    async def get_derivation_record(
        self, index: uint32, wallet_id: uint32
    ) -> Optional[DerivationRecord]:
        """
        Returns the derivation record by index and wallet id.
        """
        cursor = await self.db_connection.execute(
            "SELECT * FROM derivation_paths WHERE derivation_index=? and wallet_id=?;",
            (index, wallet_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None and row[0] is not None:
            return DerivationRecord(
                row[0],
                bytes.fromhex(row[2]),
                PublicKey.from_bytes(bytes.fromhex(row[1])),
                row[3],
                row[4],
            )

        return None

    async def get_derivation_record_for_puzzle_hash(
        self, puzzle_hash: str
    ) -> Optional[DerivationRecord]:
        """
        Returns the derivation record by index and wallet id.
        """
        cursor = await self.db_connection.execute(
            "SELECT * FROM derivation_paths WHERE puzzle_hash=?;", (puzzle_hash,),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None and row[0] is not None:
            return DerivationRecord(
                row[0],
                bytes.fromhex(row[2]),
                PublicKey.from_bytes(bytes.fromhex(row[1])),
                row[3],
                row[4],
            )

        return None

    async def set_used_up_to(self, index: uint32) -> None:
        """
        Sets a derivation path to used so we don't use it again.
        """
        pass
        cursor = await self.db_connection.execute(
            "UPDATE derivation_paths SET used=1 WHERE derivation_index<=?", (index,),
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
        row = await cursor.fetchone()
        await cursor.close()

        return row is not None

    async def index_for_pubkey(self, pubkey: PublicKey) -> Optional[uint32]:
        """
        Returns derivation paths for the given pubkey.
        Returns None if not present.
        """

        cursor = await self.db_connection.execute(
            "SELECT * from derivation_paths WHERE pubkey=?", (bytes(pubkey).hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None:
            return uint32(row[0])

        return None

    async def index_for_puzzle_hash(self, puzzle_hash: bytes32) -> Optional[uint32]:
        """
        Returns the derivation path for the puzzle_hash.
        Returns None if not present.
        """
        cursor = await self.db_connection.execute(
            "SELECT * from derivation_paths WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None:
            return uint32(row[0])

        return None

    async def wallet_info_for_puzzle_hash(
        self, puzzle_hash: bytes32
    ) -> Optional[Tuple[uint32, WalletType]]:
        """
        Returns the derivation path for the puzzle_hash.
        Returns None if not present.
        """

        cursor = await self.db_connection.execute(
            "SELECT * from derivation_paths WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None:
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

    async def get_last_derivation_path(self) -> Optional[uint32]:
        """
        Returns the last derivation path by derivation_index.
        """

        cursor = await self.db_connection.execute(
            "SELECT MAX(derivation_index) FROM derivation_paths;"
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None and row[0] is not None:
            return uint32(row[0])

        return None

    async def get_last_derivation_path_for_wallet(
        self, wallet_id: int
    ) -> Optional[uint32]:
        """
        Returns the last derivation path by derivation_index.
        """

        cursor = await self.db_connection.execute(
            f"SELECT MAX(derivation_index) FROM derivation_paths WHERE wallet_id={wallet_id};"
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None and row[0] is not None:
            return uint32(row[0])

        return None

    async def get_unused_derivation_path(self) -> Optional[uint32]:
        """
        Returns the first unused derivation path by derivation_index.
        """
        cursor = await self.db_connection.execute(
            "SELECT MIN(derivation_index) FROM derivation_paths WHERE used=0;"
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is not None and row[0] is not None:
            return uint32(row[0])

        return None
