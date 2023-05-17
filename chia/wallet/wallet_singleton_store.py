from __future__ import annotations

import dataclasses
import json
from sqlite3 import Row
from typing import List, Optional, Type, TypeVar, Union

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.ints import uint32, uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.singleton_coin_record import SingletonCoinRecord

_T_WalletSingletonStore = TypeVar("_T_WalletSingletonStore", bound="WalletSingletonStore")


def _row_to_singleton_record(row: Row) -> SingletonCoinRecord:
    return SingletonCoinRecord(
        coin=Coin.from_json_dict(json.loads(row[1])),
        singleton_id=bytes32(row[2]),
        wallet_id=uint32(row[3]),
        parent_coin_spend=CoinSpend.from_bytes(row[4]),
        inner_puzzle_hash=bytes32(row[5]),
        confirmed=bool(row[6]),
        confirmed_at_height=uint32(row[7]),
        spent_height=uint32(row[8]),
        lineage_proof=LineageProof.from_bytes(row[9]),
        custom_data=row[10],
        generation=uint32(row[11]),
        timestamp=uint64(row[12]),
    )


class WalletSingletonStore:
    """
    WalletSingletonStore keeps track of all user created singletons and necessary wallet data

    Coins can be added as 'confirmed=False' when they are created in a wallet transaction. Once the
    transaction is confirmed, the wallet should update to 'confirmed=True'.
    """

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls: Type[_T_WalletSingletonStore], wrapper: DBWrapper2) -> _T_WalletSingletonStore:
        self = cls()
        self.db_wrapper = wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                (
                    "CREATE TABLE IF NOT EXISTS singletons("
                    "coin_id blob PRIMARY KEY,"
                    " coin text,"
                    " singleton_id blob,"
                    " wallet_id int,"
                    " parent_coin_spend blob,"
                    " inner_puzzle_hash blob,"
                    " confirmed tinyint,"
                    " confirmed_at_height int,"
                    " spent_height int,"
                    " lineage_proof blob,"
                    " custom_data blob,"
                    " generation int,"
                    " timestamp int)"
                )
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS singleton_id_index ON singletons(singleton_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS wallet_id_index ON singletons(wallet_id)")

            await conn.execute(
                "CREATE INDEX IF NOT EXISTS confirmed_at_height_index " "ON singletons(confirmed_at_height)"
            )

        return self

    async def _clear_database(self) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM singletons")).close()

    async def add_singleton_record(self, record: SingletonCoinRecord) -> None:
        """
        Store SingletonCoinRecord in DB
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            columns = (
                "coin_id, coin, singleton_id, wallet_id, parent_coin_spend, inner_puzzle_hash, "
                "confirmed, confirmed_at_height, spent_height, lineage_proof, custom_data, "
                "generation, timestamp"
            )
            await conn.execute(
                f"INSERT or REPLACE INTO singletons ({columns}) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.name(),
                    json.dumps(record.coin.to_json_dict()),
                    record.singleton_id,
                    record.wallet_id,
                    bytes(record.parent_coin_spend),
                    record.inner_puzzle_hash,
                    int(record.confirmed),
                    record.confirmed_at_height,
                    record.spent_height,
                    bytes(record.lineage_proof),
                    record.custom_data,
                    record.generation,
                    record.timestamp,
                ),
            )

    async def get_records_by_singleton_id(
        self,
        singleton_id: bytes32,
        min_generation: Optional[uint32] = None,
        max_generation: Optional[uint32] = None,
        num_results: Optional[uint32] = None,
    ) -> List[SingletonCoinRecord]:
        """
        Retrieves all stored singletons for a singleton ID.
        """
        query_params: List[Union[bytes32, uint32]] = [singleton_id]
        for optional_param in (min_generation, max_generation, num_results):
            if optional_param is not None:
                query_params.append(optional_param)

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * from singletons WHERE singleton_id=? "
                f"{'AND generation >=? ' if min_generation is not None else ''}"
                f"{'AND generation <=? ' if max_generation is not None else ''}"
                "ORDER BY generation DESC"
                f"{' LIMIT ?' if num_results is not None else ''}",
                tuple(query_params),
            )
        records = []
        for row in rows:
            records.append(_row_to_singleton_record(row))

        return records

    async def get_record_by_coin_id(self, coin_id: bytes32) -> Optional[SingletonCoinRecord]:
        """
        Check for a record with coin ID and return it if present
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn,
                "SELECT * FROM singletons WHERE coin_id = ?",
                (coin_id,),
            )
        if row is not None:
            return _row_to_singleton_record(row)
        return None

    async def get_latest_singleton(
        self, singleton_id: bytes32, only_confirmed: bool = False
    ) -> Optional[SingletonCoinRecord]:
        """
        Check for a record with coin ID and return the most recent if present
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            if only_confirmed:
                cursor = await conn.execute(
                    "SELECT * from singletons WHERE singleton_id=? and confirmed=1 ORDER BY generation DESC LIMIT 1",
                    (singleton_id,),
                )
            else:
                cursor = await conn.execute(
                    "SELECT * from singletons WHERE singleton_id=? ORDER BY generation DESC LIMIT 1",
                    (singleton_id,),
                )
            row = await cursor.fetchone()
            await cursor.close()
        if row is not None:
            return _row_to_singleton_record(row)
        return None

    async def get_unconfirmed_singletons(self, singleton_id: bytes32) -> List[SingletonCoinRecord]:
        """
        Returns all singletons with a specific id that are unconfirmed
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * from singletons WHERE singleton_id=? AND confirmed=0", (singleton_id,)
            )
        records = [_row_to_singleton_record(row) for row in rows]
        return records

    async def set_confirmed(self, coin_id: bytes32, confirmed_height: uint32, timestamp: uint64) -> None:
        """
        Updates a record to set confirmed=True, and add the confirmed height
        """
        current: Optional[SingletonCoinRecord] = await self.get_record_by_coin_id(coin_id)
        if current is None or (current.confirmed_at_height == confirmed_height and current.confirmed):
            return

        await self.add_singleton_record(
            dataclasses.replace(current, confirmed=True, confirmed_at_height=confirmed_height, timestamp=timestamp)
        )

        # update the parent record spent_height
        parent_id = current.coin.parent_coin_info
        parent: Optional[SingletonCoinRecord] = await self.get_record_by_coin_id(parent_id)
        if parent is None:
            return
        await self.add_singleton_record(dataclasses.replace(parent, spent_height=confirmed_height))

    async def set_spent(self, coin_id: bytes32, spent_height: uint32, timestamp: uint64) -> None:
        """
        Updates a confirmed record with a spent_height
        """
        current: Optional[SingletonCoinRecord] = await self.get_record_by_coin_id(coin_id)
        if current is None:
            return

        await self.add_singleton_record(
            dataclasses.replace(current, confirmed=True, spent_height=spent_height, timestamp=timestamp)
        )

    async def delete_records_by_singleton_id(self, singleton_id: bytes32) -> None:
        """
        Delete all records with a given singleton ID
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM singletons WHERE singleton_id=?", (singleton_id,))).close()

    async def delete_record_by_coin_id(self, coin_id: bytes32) -> None:
        """
        Delete a record for a given coin ID
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await (await conn.execute("DELETE FROM singletons WHERE coin_id=?", (coin_id,))).close()
