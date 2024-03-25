from __future__ import annotations

import json
import logging
from sqlite3 import Row
from typing import List, Optional, Type, TypeVar, Union

from clvm.casts import int_from_bytes

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.condition_tools import conditions_dict_for_solution
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.ints import uint32, uint64
from chia.wallet import singleton
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.singleton import get_inner_puzzle_from_singleton, get_singleton_id_from_puzzle
from chia.wallet.singleton_record import SingletonRecord

log = logging.getLogger(__name__)
_T_WalletSingletonStore = TypeVar("_T_WalletSingletonStore", bound="WalletSingletonStore")


class WalletSingletonStore:
    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls: Type[_T_WalletSingletonStore], wrapper: DBWrapper2) -> _T_WalletSingletonStore:
        self = cls()
        self.db_wrapper = wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS singletons("
                "coin_id blob PRIMARY KEY,"
                " coin text,"
                " singleton_id blob,"
                " wallet_id int,"
                " parent_coin_spend blob,"
                " inner_puzzle_hash blob,"
                " pending tinyint,"
                " removed_height int,"
                " lineage_proof blob,"
                " custom_data blob)"
            )

            await conn.execute("CREATE INDEX IF NOT EXISTS removed_height_index on singletons(removed_height)")

        return self

    async def save_singleton(self, record: SingletonRecord) -> None:
        singleton_id = singleton.get_singleton_id_from_puzzle(record.parent_coinspend.puzzle_reveal)
        if singleton_id is None:  # pragma: no cover
            raise RuntimeError(
                "Failed to derive Singleton ID from puzzle reveal in parent spend %s", record.parent_coinspend
            )
        pending_int = 0
        if record.pending:
            pending_int = 1
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            columns = (
                "coin_id, coin, singleton_id, wallet_id, parent_coin_spend, inner_puzzle_hash, "
                "pending, removed_height, lineage_proof, custom_data"
            )
            await conn.execute(
                f"INSERT or REPLACE INTO singletons ({columns}) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.coin.name().hex(),
                    json.dumps(record.coin.to_json_dict()),
                    singleton_id.hex(),
                    record.wallet_id,
                    bytes(record.parent_coinspend),
                    record.inner_puzzle_hash,
                    pending_int,
                    record.removed_height,
                    bytes(record.lineage_proof),
                    record.custom_data,
                ),
            )

    async def add_spend(
        self,
        wallet_id: uint32,
        coin_state: CoinSpend,
        block_height: uint32 = uint32(0),
        pending: bool = True,
    ) -> None:
        """Given a coin spend of a singleton, attempt to calculate the child coin and details
        for the new singleton record. Add the new record to the store and remove the old record
        if it exists
        """
        # get singleton_id from puzzle_reveal
        singleton_id = get_singleton_id_from_puzzle(coin_state.puzzle_reveal)
        if not singleton_id:
            raise RuntimeError("Coin to add is not a valid singleton")

        # get details for singleton record
        conditions = conditions_dict_for_solution(
            coin_state.puzzle_reveal, coin_state.solution, DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM
        )

        cc_cond = [cond for cond in conditions[ConditionOpcode.CREATE_COIN] if int_from_bytes(cond.vars[1]) % 2 == 1][0]

        coin = Coin(coin_state.coin.name(), cc_cond.vars[0], uint64(int_from_bytes(cc_cond.vars[1])))
        inner_puz = get_inner_puzzle_from_singleton(coin_state.puzzle_reveal)
        if inner_puz is None:  # pragma: no cover
            raise RuntimeError("Could not get inner puzzle from puzzle reveal in coin spend %s", coin_state)

        lineage_bytes = [x.as_atom() for x in coin_state.solution.to_program().first().as_iter()]
        if len(lineage_bytes) == 2:
            lineage_proof = LineageProof(bytes32(lineage_bytes[0]), None, uint64(int_from_bytes(lineage_bytes[1])))
        else:
            lineage_proof = LineageProof(
                bytes32(lineage_bytes[0]), bytes32(lineage_bytes[1]), uint64(int_from_bytes(lineage_bytes[2]))
            )
        # Create and save the new singleton record
        new_record = SingletonRecord(
            coin, singleton_id, wallet_id, coin_state, inner_puz.get_tree_hash(), pending, 0, lineage_proof, None
        )
        await self.save_singleton(new_record)
        # check if coin is in DB and mark deleted if found
        current_records = await self.get_records_by_coin_id(coin_state.coin.name())
        if len(current_records) > 0:
            await self.delete_singleton_by_coin_id(coin_state.coin.name(), block_height)
        return

    def _to_singleton_record(self, row: Row) -> SingletonRecord:
        return SingletonRecord(
            coin=Coin.from_json_dict(json.loads(row[1])),
            singleton_id=bytes32.from_hexstr(row[2]),
            wallet_id=uint32(row[3]),
            parent_coinspend=CoinSpend.from_bytes(row[4]),
            inner_puzzle_hash=bytes32.from_bytes(row[5]),  # inner puz hash
            pending=True if row[6] == 1 else False,
            removed_height=uint32(row[7]),
            lineage_proof=LineageProof.from_bytes(row[8]),
            custom_data=row[9],
        )

    async def delete_singleton_by_singleton_id(self, singleton_id: bytes32, height: uint32) -> bool:
        """Tries to mark a given singleton as deleted at specific height

        This is due to how re-org works
        Returns `True` if singleton was found and marked deleted or `False` if not."""
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "UPDATE singletons SET removed_height=? WHERE singleton_id=?", (int(height), singleton_id.hex())
            )
            if cursor.rowcount > 0:
                log.info("Deleted singleton with singleton id: %s", singleton_id.hex())
                return True
            log.warning("Couldn't find singleton with singleton id to delete: %s", singleton_id.hex())
            return False

    async def delete_singleton_by_coin_id(self, coin_id: bytes32, height: uint32) -> bool:
        """Tries to mark a given singleton as deleted at specific height

        This is due to how re-org works
        Returns `True` if singleton was found and marked deleted or `False` if not."""
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "UPDATE singletons SET removed_height=? WHERE coin_id=?", (int(height), coin_id.hex())
            )
            if cursor.rowcount > 0:
                log.info("Deleted singleton with coin id: %s", coin_id.hex())
                return True
            log.warning("Couldn't find singleton with coin id to delete: %s", coin_id.hex())
            return False

    async def delete_wallet(self, wallet_id: uint32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute("DELETE FROM singletons WHERE wallet_id=?", (wallet_id,))
            await cursor.close()

    async def update_pending_transaction(self, coin_id: bytes32, pending: bool) -> bool:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            c = await conn.execute(
                "UPDATE singletons SET pending=? WHERE coin_id = ?",
                (pending, coin_id.hex()),
            )
            return c.rowcount > 0

    async def get_records_by_wallet_id(self, wallet_id: int) -> List[SingletonRecord]:
        """
        Retrieves all entries for a wallet ID.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM singletons WHERE wallet_id = ? ORDER BY removed_height",
                (wallet_id,),
            )
        return [self._to_singleton_record(row) for row in rows]

    async def get_records_by_coin_id(self, coin_id: bytes32) -> List[SingletonRecord]:
        """
        Retrieves all entries for a coin ID.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM singletons WHERE coin_id = ?",
                (coin_id.hex(),),
            )
        return [self._to_singleton_record(row) for row in rows]

    async def get_records_by_singleton_id(self, singleton_id: bytes32) -> List[SingletonRecord]:
        """
        Retrieves all entries for a singleton ID.
        """

        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                "SELECT * FROM singletons WHERE singleton_id = ? ORDER BY removed_height",
                (singleton_id.hex(),),
            )
        return [self._to_singleton_record(row) for row in rows]

    async def rollback(self, height: int, wallet_id_arg: int) -> None:
        """
        Rollback removes all entries which have entry_height > height passed in. Note that this is not committed to the
        DB until db_wrapper.commit() is called. However, it is written to the cache, so it can be fetched with
        get_all_state_transitions.
        """

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "DELETE FROM singletons WHERE removed_height>? AND wallet_id=?", (height, wallet_id_arg)
            )
            await cursor.close()

    async def count(self, wallet_id: Optional[uint32] = None) -> int:
        sql = "SELECT COUNT(singleton_id) FROM singletons WHERE removed_height=0"
        params: List[uint32] = []
        if wallet_id is not None:
            sql += " AND wallet_id=?"
            params.append(wallet_id)
        async with self.db_wrapper.reader_no_transaction() as conn:
            count_row = await execute_fetchone(conn, sql, params)
            if count_row:
                return int(count_row[0])
        return -1  # pragma: no cover

    async def is_empty(self, wallet_id: Optional[uint32] = None) -> bool:
        sql = "SELECT 1 FROM singletons WHERE removed_height=0"
        params: List[Union[uint32, bytes32]] = []
        if wallet_id is not None:
            sql += " AND wallet_id=?"
            params.append(wallet_id)
        sql += " LIMIT 1"
        async with self.db_wrapper.reader_no_transaction() as conn:
            count_row = await execute_fetchone(conn, sql, params)
            if count_row:
                return False
        return True
