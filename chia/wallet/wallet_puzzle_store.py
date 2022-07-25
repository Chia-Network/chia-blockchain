import asyncio
import logging
from typing import List, Optional, Set, Tuple

from blspy import G1Element

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.ints import uint32
from chia.util.lru_cache import LRUCache
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.util.wallet_types import WalletType

log = logging.getLogger(__name__)


class WalletPuzzleStore:
    """
    WalletPuzzleStore keeps track of all generated puzzle_hashes and their derivation path / wallet.
    This is only used for HD wallets where each address is derived from a public key. Otherwise, use the
    WalletInterestedStore to keep track of puzzle hashes which we are interested in.
    """

    lock: asyncio.Lock
    cache_size: uint32
    all_puzzle_hashes: Set[bytes32]
    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2, cache_size: uint32 = uint32(600000)):
        self = cls()

        self.cache_size = cache_size

        self.db_wrapper = db_wrapper
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS derivation_paths("
                    "derivation_index int,"
                    " pubkey text,"
                    " puzzle_hash text PRIMARY KEY,"
                    " wallet_type int,"
                    " wallet_id int,"
                    " used tinyint,"
                    " hardened tinyint)"
                )
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS derivation_index_index on derivation_paths(derivation_index)"
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS ph on derivation_paths(puzzle_hash)")

            await conn.execute("CREATE INDEX IF NOT EXISTS pubkey on derivation_paths(pubkey)")

            await conn.execute("CREATE INDEX IF NOT EXISTS wallet_type on derivation_paths(wallet_type)")

            await conn.execute("CREATE INDEX IF NOT EXISTS derivation_paths_wallet_id on derivation_paths(wallet_id)")

            await conn.execute("CREATE INDEX IF NOT EXISTS used on derivation_paths(wallet_type)")

        # Lock
        self.lock = asyncio.Lock()  # external
        await self._init_cache()
        return self

    async def _init_cache(self):
        self.all_puzzle_hashes = await self.get_all_puzzle_hashes()
        # self.get_last_derivation_path_for_wallet_cache = LRUCache(100)
        self.wallet_info_for_ph_cache = LRUCache(100)

    async def add_derivation_paths(self, records: List[DerivationRecord]) -> None:
        """
        Insert many derivation paths into the database.
        """
        if len(records) == 0:
            return
        sql_records = []
        for record in records:
            log.debug("Adding derivation record: %s", record)
            self.all_puzzle_hashes.add(record.puzzle_hash)
            if record.hardened:
                hardened = 1
            else:
                hardened = 0
            sql_records.append(
                (
                    record.index,
                    bytes(record.pubkey).hex(),
                    record.puzzle_hash.hex(),
                    record.wallet_type,
                    record.wallet_id,
                    0,
                    hardened,
                ),
            )

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (
                await conn.executemany(
                    "INSERT OR REPLACE INTO derivation_paths VALUES(?, ?, ?, ?, ?, ?, ?)",
                    sql_records,
                )
            ).close()

    async def get_derivation_record(
        self, index: uint32, wallet_id: uint32, hardened: bool
    ) -> Optional[DerivationRecord]:
        """
        Returns the derivation record by index and wallet id.
        """
        if hardened:
            hard = 1
        else:
            hard = 0
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn,
                "SELECT derivation_index, pubkey, puzzle_hash, wallet_type, wallet_id, used FROM derivation_paths "
                "WHERE derivation_index=? AND wallet_id=? AND hardened=?",
                (index, wallet_id, hard),
            )

        if row is not None and row[0] is not None:
            return self.row_to_record(row)

        return None

    async def get_derivation_record_for_puzzle_hash(self, puzzle_hash: bytes32) -> Optional[DerivationRecord]:
        """
        Returns the derivation record by index and wallet id.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn,
                "SELECT derivation_index, pubkey, puzzle_hash, wallet_type, wallet_id, hardened FROM derivation_paths "
                "WHERE puzzle_hash=?",
                (puzzle_hash.hex(),),
            )

        if row is not None and row[0] is not None:
            return self.row_to_record(row)

        return None

    async def set_used_up_to(self, index: uint32) -> None:
        """
        Sets a derivation path to used so we don't use it again.
        """

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (
                await conn.execute(
                    "UPDATE derivation_paths SET used=1 WHERE derivation_index<=?",
                    (index,),
                )
            ).close()

    async def puzzle_hash_exists(self, puzzle_hash: bytes32) -> bool:
        """
        Checks if passed puzzle_hash is present in the db.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn, "SELECT puzzle_hash FROM derivation_paths WHERE puzzle_hash=?", (puzzle_hash.hex(),)
            )

        return row is not None

    async def one_of_puzzle_hashes_exists(self, puzzle_hashes: List[bytes32]) -> bool:
        """
        Checks if one of the passed puzzle_hashes is present in the db.
        """
        if len(puzzle_hashes) < 1:
            return False

        for ph in puzzle_hashes:
            if ph in self.all_puzzle_hashes:
                return True

        return False

    def row_to_record(self, row) -> DerivationRecord:
        return DerivationRecord(
            uint32(row[0]),
            bytes32.fromhex(row[2]),
            G1Element.from_bytes(bytes.fromhex(row[1])),
            WalletType(row[3]),
            uint32(row[4]),
            bool(row[5]),
        )

    async def index_for_pubkey(self, pubkey: G1Element) -> Optional[uint32]:
        """
        Returns derivation paths for the given pubkey.
        Returns None if not present.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn, "SELECT derivation_index FROM derivation_paths WHERE pubkey=?", (bytes(pubkey).hex(),)
            )

        if row is not None:
            return uint32(row[0])

        return None

    async def record_for_pubkey(self, pubkey: G1Element) -> Optional[DerivationRecord]:
        """
        Returns derivation record for the given pubkey.
        Returns None if not present.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn,
                "SELECT derivation_index, pubkey, puzzle_hash, wallet_type, wallet_id, hardened "
                "FROM derivation_paths "
                "WHERE pubkey=?",
                (bytes(pubkey).hex(),),
            )

        return None if row is None else self.row_to_record(row)

    async def index_for_puzzle_hash(self, puzzle_hash: bytes32) -> Optional[uint32]:
        """
        Returns the derivation path for the puzzle_hash.
        Returns None if not present.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn, "SELECT derivation_index FROM derivation_paths WHERE puzzle_hash=?", (puzzle_hash.hex(),)
            )
        return None if row is None else uint32(row[0])

    async def record_for_puzzle_hash(self, puzzle_hash: bytes32) -> Optional[DerivationRecord]:
        """
        Returns the derivation path for the puzzle_hash.
        Returns None if not present.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn,
                "SELECT derivation_index, pubkey, puzzle_hash, wallet_type, wallet_id, hardened "
                "FROM derivation_paths "
                "WHERE puzzle_hash=?",
                (puzzle_hash.hex(),),
            )

        if row is not None and row[0] is not None:
            return self.row_to_record(row)

        return None

    async def index_for_puzzle_hash_and_wallet(self, puzzle_hash: bytes32, wallet_id: uint32) -> Optional[uint32]:
        """
        Returns the derivation path for the puzzle_hash.
        Returns None if not present.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn,
                "SELECT derivation_index FROM derivation_paths WHERE puzzle_hash=? AND wallet_id=?;",
                (
                    puzzle_hash.hex(),
                    wallet_id,
                ),
            )

        if row is not None:
            return uint32(row[0])

        return None

    async def wallet_info_for_puzzle_hash(self, puzzle_hash: bytes32) -> Optional[Tuple[int, WalletType]]:
        """
        Returns the derivation path for the puzzle_hash.
        Returns None if not present.
        """
        cached = self.wallet_info_for_ph_cache.get(puzzle_hash)
        if cached is not None:
            return cached

        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn, "SELECT wallet_type, wallet_id FROM derivation_paths WHERE puzzle_hash=?", (puzzle_hash.hex(),)
            )

        if row is not None:
            self.wallet_info_for_ph_cache.put(puzzle_hash, (row[1], WalletType(row[0])))
            return row[1], WalletType(row[0])

        return None

    async def get_all_puzzle_hashes(self) -> Set[bytes32]:
        """
        Return a set containing all puzzle_hashes we generated.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall("SELECT puzzle_hash FROM derivation_paths")
            return set(bytes32.fromhex(row[0]) for row in rows)

    async def get_last_derivation_path(self) -> Optional[uint32]:
        """
        Returns the last derivation path by derivation_index.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(conn, "SELECT MAX(derivation_index) FROM derivation_paths")
            return None if row is None or row[0] is None else uint32(row[0])

    async def get_last_derivation_path_for_wallet(self, wallet_id: int) -> Optional[uint32]:
        """
        Returns the last derivation path by derivation_index.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn, "SELECT MAX(derivation_index) FROM derivation_paths WHERE wallet_id=?", (wallet_id,)
            )
            return None if row is None or row[0] is None else uint32(row[0])

    async def get_current_derivation_record_for_wallet(self, wallet_id: uint32) -> Optional[DerivationRecord]:
        """
        Returns the current derivation record by derivation_index.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn,
                "SELECT MAX(derivation_index) FROM derivation_paths WHERE wallet_id=? AND used=1 AND hardened=0",
                (wallet_id,),
            )

        if row is not None and row[0] is not None:
            index = uint32(row[0])
            return await self.get_derivation_record(index, wallet_id, False)

        return None

    async def get_unused_derivation_path(self) -> Optional[uint32]:
        """
        Returns the first unused derivation path by derivation_index.
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn, "SELECT MIN(derivation_index) FROM derivation_paths WHERE used=0 AND hardened=0;"
            )

        if row is not None and row[0] is not None:
            return uint32(row[0])

        return None
