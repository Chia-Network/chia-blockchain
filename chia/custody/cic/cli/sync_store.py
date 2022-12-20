import aiosqlite
import dataclasses

from blspy import G1Element
from pathlib import Path
from typing import List, Optional, Tuple, Union

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32, uint64
from chia.wallet.lineage_proof import LineageProof

from cic.cli.record_types import SingletonRecord, ACHRecord, RekeyRecord
from cic.drivers.prefarm import SpendType
from cic.drivers.prefarm_info import PrefarmInfo
from cic.drivers.puzzle_root_construction import RootDerivation, calculate_puzzle_root


class SyncStore:
    db_connection: aiosqlite.Connection
    db_wrapper: DBWrapper

    @classmethod
    async def create(cls, db_path: Path):
        self = cls()

        wrapper = DBWrapper(await aiosqlite.connect(db_path))
        self.db_connection = wrapper.db
        self.db_wrapper = wrapper

        await self.db_connection.execute(
            "CREATE TABLE IF NOT EXISTS singletons("
            "   coin_id blob PRIMARY KEY,"
            "   parent_id blob,"
            "   puzzle_hash blob,"
            "   amount blob,"
            "   puzzle_root blob,"
            "   lineage_proof blob,"
            "   confirmed_at_time bigint,"
            "   generation bigint,"
            "   puzzle_reveal blob,"
            "   solution blob,"
            "   spend_type int,"
            "   spending_pubkey blob"
            ")"
        )

        await self.db_connection.execute(
            "CREATE TABLE IF NOT EXISTS p2_singletons("
            "   coin_id blob PRIMARY KEY,"
            "   parent_id blob,"
            "   puzzle_hash blob,"
            "   amount blob,"
            "   spent tinyint"
            ")"
        )

        await self.db_connection.execute(
            "CREATE TABLE IF NOT EXISTS achs("
            "   coin_id blob PRIMARY KEY,"
            "   parent_id blob,"
            "   puzzle_hash blob,"
            "   amount blob,"
            "   from_root blob,"
            "   p2_ph blob,"
            "   confirmed_at_time bigint,"
            "   spent_at_height bigint,"
            "   completed tinyint,"
            "   spending_pubkey blob"
            ")"
        )

        await self.db_connection.execute(
            "CREATE TABLE IF NOT EXISTS rekeys("
            "   coin_id blob PRIMARY KEY,"
            "   parent_id blob,"
            "   puzzle_hash blob,"
            "   amount blob,"
            "   from_root blob,"
            "   to_root blob,"
            "   timelock blob,"
            "   confirmed_at_time bigint,"
            "   spent_at_height bigint,"
            "   completed tinyint,"
            "   spending_pubkey blob"
            ")"
        )

        await self.db_connection.execute(
            "CREATE TABLE IF NOT EXISTS configuration_info("
            "   launcher_id blob PRIMARY KEY,"  # This table should only ever have one entry
            "   info blob,"
            "   outdated tinyint"
            ")"
        )
        await self.db_connection.commit()
        return self

    async def add_singleton_record(self, record: SingletonRecord) -> None:
        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO singletons VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.coin.name(),
                record.coin.parent_coin_info,
                record.coin.puzzle_hash,
                bytes(record.coin.amount),
                record.puzzle_root,
                bytes(record.lineage_proof),
                record.confirmed_at_time,
                record.generation,
                bytes([0]) if record.puzzle_reveal is None else bytes(record.puzzle_reveal),
                bytes([0]) if record.solution is None else bytes(record.solution),
                0 if record.spend_type is None else record.spend_type.value,
                bytes([0]) if record.spending_pubkey is None else bytes(record.spending_pubkey),
            ),
        )
        await cursor.close()

    async def add_ach_record(self, record: ACHRecord) -> None:
        completed_int: int
        if record.completed:
            completed_int = 1
        elif record.completed is None:
            completed_int = 0
        else:
            completed_int = -1
        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO achs VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.coin.name(),
                record.coin.parent_coin_info,
                record.coin.puzzle_hash,
                bytes(record.coin.amount),
                record.from_root,
                record.p2_ph,
                record.confirmed_at_time,
                0 if record.spent_at_height is None else record.spent_at_height,
                completed_int,
                b"" if record.clawback_pubkey is None else bytes(record.clawback_pubkey),
            ),
        )
        await cursor.close()

    async def add_rekey_record(self, record: RekeyRecord) -> None:
        completed_int: int
        if record.completed:
            completed_int = 1
        elif record.completed is None:
            completed_int = 0
        else:
            completed_int = -1
        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO rekeys VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.coin.name(),
                record.coin.parent_coin_info,
                record.coin.puzzle_hash,
                bytes(record.coin.amount),
                record.from_root,
                record.to_root,
                record.timelock,
                record.confirmed_at_time,
                0 if record.spent_at_height is None else record.spent_at_height,
                completed_int,
                b"" if record.clawback_pubkey is None else bytes(record.clawback_pubkey),
            ),
        )
        await cursor.close()

    async def add_p2_singletons(self, coins: List[Coin]) -> None:
        for p2_singleton in coins:
            cursor = await self.db_connection.execute(
                "INSERT OR REPLACE INTO p2_singletons VALUES(?, ?, ?, ?, ?)",
                (
                    p2_singleton.name(),
                    p2_singleton.parent_coin_info,
                    p2_singleton.puzzle_hash,
                    bytes(p2_singleton.amount),
                    0,
                ),
            )
        if len(coins) > 0:
            await cursor.close()

    async def set_p2_singleton_spent(self, coin_id: bytes32) -> None:
        cursor = await self.db_connection.execute("UPDATE p2_singletons SET spent = 1 WHERE coin_id==?", (coin_id,))
        await cursor.close()

    def _singleton_record_from_row(self, record) -> SingletonRecord:
        return SingletonRecord(
            Coin(
                record[1],
                record[2],
                uint64.from_bytes(record[3]),
            ),
            record[4],
            LineageProof.from_bytes(record[5]),
            uint64(record[6]),
            uint32(record[7]),
            None if record[8] == bytes([0]) else SerializedProgram.from_bytes(record[8]),
            None if record[9] == bytes([0]) else SerializedProgram.from_bytes(record[9]),
            None if record[10] == 0 else SpendType(record[10]),
            None if record[11] == bytes([0]) else G1Element.from_bytes(record[11]),
        )

    async def get_latest_singleton(self) -> Optional[SingletonRecord]:
        cursor = await self.db_connection.execute("SELECT * from singletons ORDER BY generation DESC LIMIT 1")
        record = await cursor.fetchone()
        await cursor.close()
        return self._singleton_record_from_row(record) if record is not None else None

    async def get_singleton_record(self, coin_id: bytes32) -> Optional[SingletonRecord]:
        cursor = await self.db_connection.execute("SELECT * from singletons WHERE coin_id=?", (coin_id,))
        record = await cursor.fetchone()
        await cursor.close()
        return self._singleton_record_from_row(record) if record is not None else None

    async def get_all_singletons(self) -> List[SingletonRecord]:
        cursor = await self.db_connection.execute("SELECT * from singletons")
        records = await cursor.fetchall()
        return [self._singleton_record_from_row(record) for record in records]

    async def get_ach_records(self, include_completed_coins: bool = False) -> List[ACHRecord]:
        optional_unspent_str: str = "" if include_completed_coins else " WHERE completed==0"
        cursor = await self.db_connection.execute(
            f"SELECT * from achs{optional_unspent_str} ORDER BY confirmed_at_time DESC"
        )
        records = await cursor.fetchall()
        await cursor.close()
        return [
            ACHRecord(
                Coin(
                    record[1],
                    record[2],
                    uint64.from_bytes(record[3]),
                ),
                bytes32(record[4]),
                bytes32(record[5]),
                uint64(record[6]),
                None if record[7] == 0 else uint32(record[7]),
                None if record[8] == 0 else record[8] == 1,
                None if record[9] == b"" else G1Element.from_bytes(record[9]),
            )
            for record in records
        ]

    async def get_rekey_records(self, include_completed_coins: bool = False) -> List[RekeyRecord]:
        optional_unspent_str: str = "" if include_completed_coins else " WHERE completed==0"
        cursor = await self.db_connection.execute(
            f"SELECT * from rekeys{optional_unspent_str} ORDER BY confirmed_at_time DESC"
        )
        records = await cursor.fetchall()
        await cursor.close()
        return [
            RekeyRecord(
                Coin(
                    record[1],
                    record[2],
                    uint64.from_bytes(record[3]),
                ),
                bytes32(record[4]),
                bytes32(record[5]),
                uint64(record[6]),
                uint64(record[7]),
                None if record[8] == 0 else uint32(record[8]),
                None if record[9] == 0 else record[9] == 1,
                None if record[10] == b"" else G1Element.from_bytes(record[10]),
            )
            for record in records
        ]

    async def get_p2_singletons(
        self, minimum_amount=uint64(0), start_end: Optional[Tuple[uint32, uint32]] = None
    ) -> List[Coin]:
        if start_end is not None:
            start, end = start_end
            limit = end - start
            limit_str: str = f" LIMIT {start}, {limit}"
        else:
            limit_str = ""
        cursor = await self.db_connection.execute(
            f"SELECT * from p2_singletons WHERE amount>=? AND spent==0 ORDER BY amount DESC{limit_str}",
            (minimum_amount,),
        )
        coins = await cursor.fetchall()
        await cursor.close()

        return [Coin(coin[1], coin[2], uint64.from_bytes(coin[3])) for coin in coins]

    async def add_configuration(
        self, configuration: Union[PrefarmInfo, RootDerivation], outdated: bool = False
    ) -> None:
        # Validate this is not a second configuration
        cursor = await self.db_connection.execute("SELECT * FROM configuration_info")
        info = await cursor.fetchone()
        await cursor.close()
        if info is not None:
            try:
                valid = PrefarmInfo.from_bytes(info[1]).is_valid_update(configuration)
            except AssertionError:
                assert isinstance(configuration, RootDerivation)
                valid = RootDerivation.from_bytes(info[1]).prefarm_info.is_valid_update(configuration.prefarm_info)
            if not valid:
                raise ValueError("The specified configuration cannot be a valid update of the existing configuration")

        # Now add it to the DB
        if isinstance(configuration, PrefarmInfo):
            launcher_id = configuration.launcher_id
        elif isinstance(configuration, RootDerivation):
            launcher_id = configuration.prefarm_info.launcher_id
        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO configuration_info VALUES(?, ?, ?)",
            (launcher_id, bytes(configuration), 1 if outdated else 0),
        )
        await cursor.close()

    async def get_configuration(
        self, public: bool, block_outdated: bool = False
    ) -> Optional[Union[PrefarmInfo, RootDerivation]]:
        cursor = await self.db_connection.execute("SELECT * FROM configuration_info")
        info = await cursor.fetchone()
        await cursor.close()

        if info is None:
            return None

        if block_outdated and info[2] == 1:
            raise ValueError("Configuration is outdated")

        try:
            derivation = RootDerivation.from_bytes(info[1])
            if public:
                return derivation.prefarm_info
            else:
                return derivation
        except AssertionError:
            if public:
                return PrefarmInfo.from_bytes(info[1])
            else:
                raise ValueError("The configuration file is not a private configuration file")

    async def is_configuration_outdated(self) -> bool:
        cursor = await self.db_connection.execute("SELECT * FROM configuration_info")
        info = await cursor.fetchone()
        await cursor.close()

        if info is None:
            raise ValueError("No configuration present")

        return True if info[2] == 1 else False

    async def update_config_puzzle_root(self, puzzle_root: bytes32, outdate_private: bool = True) -> bool:
        cursor = await self.db_connection.execute("SELECT * FROM configuration_info")
        info = await cursor.fetchone()
        await cursor.close()

        if info is None:
            raise ValueError("No configuration present")

        try:
            derivation = RootDerivation.from_bytes(info[1])
            if derivation.next_root == puzzle_root:
                new_configuration = calculate_puzzle_root(
                    derivation.prefarm_info,
                    derivation.pubkey_list,
                    derivation.required_pubkeys + 1,
                    derivation.maximum_pubkeys,
                    derivation.minimum_pubkeys,
                )
                outdate_private = False
            else:
                new_configuration = dataclasses.replace(
                    derivation, prefarm_info=dataclasses.replace(derivation.prefarm_info, puzzle_root=puzzle_root)
                )
            public = False
        except AssertionError:
            prefarm_info = PrefarmInfo.from_bytes(info[1])
            new_configuration = dataclasses.replace(prefarm_info, puzzle_root=puzzle_root)
            public = True

        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO configuration_info VALUES(?, ?, ?)",
            (info[0], bytes(new_configuration), 1 if outdate_private and not public else info[2]),
        )
        await cursor.close()

        return (outdate_private and not public) or info[2] == 1
