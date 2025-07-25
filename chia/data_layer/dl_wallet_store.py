from __future__ import annotations

import dataclasses
from typing import Optional, Union

from aiosqlite import Row
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64
from typing_extensions import Self

from chia.data_layer.data_layer_wallet import Mirror
from chia.data_layer.singleton_record import SingletonRecord
from chia.types.blockchain_format.coin import Coin
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.wallet.lineage_proof import LineageProof


def _row_to_singleton_record(row: Row) -> SingletonRecord:
    return SingletonRecord(
        bytes32(row[0]),
        bytes32(row[1]),
        bytes32(row[2]),
        bytes32(row[3]),
        bool(row[4]),
        uint32(row[5]),
        LineageProof.from_bytes(row[6]),
        uint32(row[7]),
        uint64(row[8]),
    )


def _row_to_mirror(row: Row, confirmed_at_height: Optional[uint32]) -> Mirror:
    urls: list[bytes] = []
    byte_list: bytes = row[3]
    while byte_list != b"":
        length = uint16.from_bytes(byte_list[0:2])
        url = byte_list[2 : length + 2]
        byte_list = byte_list[length + 2 :]
        urls.append(url)
    return Mirror(
        bytes32(row[0]),
        bytes32(row[1]),
        uint64.from_bytes(row[2]),
        Mirror.decode_urls(urls),
        bool(row[4]),
        confirmed_at_height,
    )


class DataLayerStore:
    """
    WalletUserStore keeps track of all user created wallets and necessary smart-contract data
    """

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2) -> Self:
        self = cls()

        self.db_wrapper = db_wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS singleton_records("
                "coin_id blob PRIMARY KEY,"
                " launcher_id blob,"
                " root blob,"
                " inner_puzzle_hash blob,"
                " confirmed tinyint,"
                " confirmed_at_height int,"
                " proof blob,"
                " generation int,"  # This first singleton will be 0, then 1, and so on.  This is handled by the DB.
                " timestamp int)"
            )

            await conn.execute(
                "CREATE TABLE IF NOT EXISTS mirrors("
                "coin_id blob PRIMARY KEY,"
                "launcher_id blob,"
                "amount blob,"
                "urls blob,"
                "ours tinyint)"
            )

            await conn.execute(
                "CREATE TABLE IF NOT EXISTS mirror_confirmations(coin_id blob PRIMARY KEY,confirmed_at_height int)"
            )

            await conn.execute(
                "CREATE INDEX IF NOT EXISTS singleton_records_launcher_id_index ON singleton_records(launcher_id)"
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS singleton_records_root_index ON singleton_records(root)")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS singleton_records_confirmed_at_height_index "
                "ON singleton_records(confirmed_at_height)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS singleton_records_generation_index ON singleton_records(generation)"
            )

            await conn.execute("CREATE TABLE IF NOT EXISTS launchers(id blob PRIMARY KEY, coin blob)")

            await conn.execute("CREATE INDEX IF NOT EXISTS mirrors_launcher_id_index ON mirrors(launcher_id)")

        return self

    async def _clear_database(self) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM singleton_records")).close()

    async def add_singleton_record(self, record: SingletonRecord) -> None:
        """
        Store SingletonRecord in DB.
        """

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute_insert(
                "INSERT OR REPLACE INTO singleton_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.coin_id,
                    record.launcher_id,
                    record.root,
                    record.inner_puzzle_hash,
                    int(record.confirmed),
                    record.confirmed_at_height,
                    bytes(record.lineage_proof),
                    record.generation,
                    record.timestamp,
                ),
            )

    async def get_all_singletons_for_launcher(
        self,
        launcher_id: bytes32,
        min_generation: Optional[uint32] = None,
        max_generation: Optional[uint32] = None,
        num_results: Optional[uint32] = None,
    ) -> list[SingletonRecord]:
        """
        Returns stored singletons with a specific launcher ID.
        """
        query_params: list[Union[bytes32, uint32]] = [launcher_id]
        for optional_param in (min_generation, max_generation, num_results):
            if optional_param is not None:
                query_params.append(optional_param)

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT * from singleton_records WHERE launcher_id=? "
                f"{'AND generation >=? ' if min_generation is not None else ''}"
                f"{'AND generation <=? ' if max_generation is not None else ''}"
                "ORDER BY generation DESC"
                f"{' LIMIT ?' if num_results is not None else ''}",
                tuple(query_params),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        records = []

        for row in rows:
            records.append(_row_to_singleton_record(row))

        return records

    async def get_singleton_record(self, coin_id: bytes32) -> Optional[SingletonRecord]:
        """
        Checks DB for SingletonRecord with coin_id: coin_id and returns it.
        """
        # if tx_id in self.tx_record_cache:
        #     return self.tx_record_cache[tx_id]

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from singleton_records WHERE coin_id=?", (coin_id,))
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            return _row_to_singleton_record(row)
        return None

    async def get_latest_singleton(
        self, launcher_id: bytes32, only_confirmed: bool = False
    ) -> Optional[SingletonRecord]:
        """
        Checks DB for SingletonRecords with launcher_id: launcher_id and returns the most recent.
        """
        # if tx_id in self.tx_record_cache:
        #     return self.tx_record_cache[tx_id]
        async with self.db_wrapper.reader_no_transaction() as conn:
            if only_confirmed:
                # get latest confirmed root
                cursor = await conn.execute(
                    "SELECT * from singleton_records WHERE launcher_id=? and confirmed = 1 "
                    "ORDER BY generation DESC LIMIT 1",
                    (launcher_id,),
                )
            else:
                cursor = await conn.execute(
                    "SELECT * from singleton_records WHERE launcher_id=? ORDER BY generation DESC LIMIT 1",
                    (launcher_id,),
                )
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            return _row_to_singleton_record(row)
        return None

    async def get_unconfirmed_singletons(self, launcher_id: bytes32) -> list[SingletonRecord]:
        """
        Returns all singletons with a specific launcher id that have not yet been marked confirmed
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT * from singleton_records WHERE launcher_id=? AND confirmed=0", (launcher_id,)
            )
            rows = await cursor.fetchall()
            await cursor.close()
        records = [_row_to_singleton_record(row) for row in rows]

        return records

    async def get_singletons_by_root(self, launcher_id: bytes32, root: bytes32) -> list[SingletonRecord]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT * from singleton_records WHERE launcher_id=? AND root=? ORDER BY generation DESC",
                (launcher_id, root),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        records = []

        for row in rows:
            records.append(_row_to_singleton_record(row))

        return records

    async def set_confirmed(self, coin_id: bytes32, height: uint32, timestamp: uint64) -> None:
        """
        Updates singleton record to be confirmed.
        """
        current: Optional[SingletonRecord] = await self.get_singleton_record(coin_id)
        if current is None or current.confirmed_at_height == height:
            return

        await self.add_singleton_record(
            dataclasses.replace(current, confirmed=True, confirmed_at_height=height, timestamp=timestamp)
        )

    async def delete_singleton_record(self, coin_id: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM singleton_records WHERE coin_id=?", (coin_id,))).close()

    async def delete_singleton_records_by_launcher_id(self, launcher_id: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM singleton_records WHERE launcher_id=?", (launcher_id,))).close()

    async def add_launcher(self, launcher: Coin, confirmed_at_height: uint32) -> None:
        """
        Add a new launcher coin's information to the DB
        """
        launcher_bytes: bytes = (
            launcher.parent_coin_info + launcher.puzzle_hash + uint64(launcher.amount).stream_to_bytes()
        )
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            launcher_id = launcher.name()
            await conn.execute_insert(
                "INSERT OR REPLACE INTO launchers VALUES (?, ?)",
                (launcher_id, launcher_bytes),
            )

    async def get_launcher(self, launcher_id: bytes32) -> Optional[Coin]:
        """
        Checks DB for a launcher with the specified ID and returns it.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT * from launchers WHERE id=?", (launcher_id,))
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            return Coin(bytes32(row[1][0:32]), bytes32(row[1][32:64]), uint64(int.from_bytes(row[1][64:72], "big")))
        return None

    async def get_all_launchers(self) -> list[bytes32]:
        """
        Checks DB for all launchers.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT id from launchers")
            rows = await cursor.fetchall()
            await cursor.close()

        return [bytes32(row[0]) for row in rows]

    async def is_launcher_tracked(self, launcher_id: bytes32) -> bool:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT COUNT(*) from singleton_records WHERE launcher_id=?", (launcher_id,))
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            count: int = row[0]
            return count > 0
        else:
            return False

    async def delete_launcher(self, launcher_id: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM launchers WHERE id=?", (launcher_id,))).close()

    async def add_mirror(self, mirror: Mirror) -> None:
        """
        Add a mirror coin to the DB
        """

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute_insert(
                "INSERT OR REPLACE INTO mirrors VALUES (?, ?, ?, ?, ?)",
                (
                    mirror.coin_id,
                    mirror.launcher_id,
                    mirror.amount.stream_to_bytes(),
                    b"".join(
                        [uint16(len(url)).stream_to_bytes() + url for url in Mirror.encode_urls(mirror.urls)]
                    ),  # prefix each item with a length
                    1 if mirror.ours else 0,
                ),
            )
            await conn.execute_insert(
                "INSERT OR REPLACE INTO mirror_confirmations (coin_id, confirmed_at_height) VALUES (?, ?)",
                (
                    mirror.coin_id,
                    mirror.confirmed_at_height,
                ),
            )

    async def get_mirrors(self, launcher_id: bytes32) -> list[Mirror]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT * from mirrors WHERE launcher_id=?",
                (launcher_id,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            mirrors: list[Mirror] = []

            for row in rows:
                confirmation_height = await execute_fetchone(
                    conn, "SELECT * FROM mirror_confirmations WHERE coin_id=?", (row[0],)
                )
                mirrors.append(
                    _row_to_mirror(row, None if confirmation_height is None else uint32(confirmation_height[1]))
                )

        return mirrors

    async def get_mirror(self, coin_id: bytes32) -> Mirror:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT * from mirrors WHERE coin_id=?",
                (coin_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            assert row is not None
            confirmation_height = await execute_fetchone(
                conn, "SELECT * FROM mirror_confirmations WHERE coin_id=?", (row[0],)
            )

        return _row_to_mirror(row, None if confirmation_height is None else uint32(confirmation_height[1]))

    async def delete_mirror(self, coin_id: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM mirrors WHERE coin_id=?", (coin_id,))).close()
            await (await conn.execute("DELETE FROM mirror_confirmations WHERE coin_id=?", (coin_id,))).close()

    async def rollback_to_block(self, height: int) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "SELECT * from mirror_confirmations WHERE confirmed_at_height>?",
                (height,),
            )
            rows = await cursor.fetchall()
            await cursor.close()

            for row in rows:
                await conn.execute(
                    "DELETE from mirror_confirmations WHERE coin_id=?",
                    (row[0],),
                )
                await conn.execute(
                    "DELETE from mirrors WHERE coin_id=?",
                    (row[0],),
                )

            cursor = await conn.execute(
                "SELECT launcher_id from singleton_records WHERE confirmed_at_height>? AND generation=0",
                (height,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            for row in rows:
                await conn.execute(
                    "DELETE from launchers WHERE id=?",
                    (row[0],),
                )

            await conn.execute(
                "UPDATE singleton_records SET "
                "confirmed_at_height = 0, confirmed = 0, timestamp = 0 WHERE confirmed_at_height > ?",
                (height,),
            )
