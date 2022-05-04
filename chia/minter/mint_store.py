import aiosqlite
from chia.minter.mint_record import MintRecord
from chia.util.db_wrapper import DBWrapper


class MintStore:
    """
    MintStore is used to queue up mint transactions and track as they are pushed for confirmation
    """

    # confirmed_at_height: uint32
    # created_at_time: uint64
    # to_puzzle_hash: bytes32
    # amount: uint64
    # fee_amount: uint64
    # confirmed: bool
    # spend_bundle: Optional[SpendBundle]
    # additions: List[Coin]
    # removals: List[Coin]
    # wallet_id: uint32
    # name: bytes32
    # depends_on: bytes32

    db_connection: aiosqlite.Connection
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()

        self.db_wrapper = db_wrapper
        self.db_connection = self.db_wrapper.db
        await self.db_connection.execute(
            (
                "CREATE TABLE IF NOT EXISTS mint_records("
                " mint_record blob,"
                " bundle_id text PRIMARY KEY,"  # NOTE: bundle_id is being stored as bytes, not hex
                " confirmed_at_height bigint,"
                " created_at_time bigint,"
                " to_puzzle_hash text,"
                " amount blob,"
                " fee_amount blob,"
                " confirmed int,"
                " depends_on text)"
            )
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS tx_confirmed_index on mint_records(confirmed_at_height)"
        )
        await self.db_connection.execute("CREATE INDEX IF NOT EXISTS depends_on on mint_records(depends_on)")

        await self.db_connection.commit()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM mint_records")
        await cursor.close()
        await self.db_connection.commit()

    async def add_mint_record(self, record: MintRecord) -> None:
        """
        Store TransactionRecord in DB and Cache.
        """
        try:
            await self.db_wrapper.lock.acquire()
            cursor = await self.db_connection.execute(
                "INSERT OR REPLACE INTO mint_records VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    bytes(record),
                    record.name,
                    record.confirmed_at_height,
                    record.created_at_time,
                    record.to_puzzle_hash.hex(),
                    bytes(record.amount),
                    bytes(record.fee_amount),
                    int(record.confirmed),
                    record.depends_on.hex(),
                ),
            )
            await cursor.close()
            await self.db_connection.commit()
        finally:
            self.db_wrapper.lock.release()
