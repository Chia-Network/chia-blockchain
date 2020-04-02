from typing import Dict, Optional, List, Set
import aiosqlite
from src.types.coin import Coin
from src.wallet.block_record import BlockRecord
from src.types.sized_bytes import bytes32
from src.util.ints import uint32
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet_coin_record import WalletCoinRecord


class WalletStore:
    """
    This object handles CoinRecords in DB used by wallet.
    """

    db_connection: aiosqlite.Connection
    coin_record_cache: Dict[str, WalletCoinRecord]
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
                f"CREATE TABLE IF NOT EXISTS coin_record("
                f"coin_name text PRIMARY KEY,"
                f" confirmed_index bigint,"
                f" spent_index bigint,"
                f" spent int,"
                f" coinbase int,"
                f" puzzle_hash text,"
                f" coin_parent text,"
                f" amount bigint,"
                f" wallet_type int,"
                f" wallet_id int)"
            )
        )
        await self.db_connection.execute(
            f"CREATE TABLE IF NOT EXISTS block_records(header_hash text PRIMARY KEY, height int,"
            f" in_lca_path tinyint, block blob)"
        )

        # Useful for reorg lookups
        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS coin_confirmed_index on coin_record(confirmed_index)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent_index on coin_record(spent_index)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent on coin_record(spent)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS coin_puzzlehash on coin_record(puzzle_hash)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS wallet_type on coin_record(wallet_type)"
        )

        await self.db_connection.execute(
            "CREATE INDEX IF NOT EXISTS wallet_id on coin_record(wallet_id)"
        )

        await self.db_connection.commit()
        self.coin_record_cache = dict()
        return self

    async def _clear_database(self):
        cursor = await self.db_connection.execute("DELETE FROM coin_record")
        await cursor.close()
        cursor_2 = await self.db_connection.execute("DELETE FROM block_records")
        await cursor_2.close()
        await self.db_connection.commit()

    # Store CoinRecord in DB and ram cache
    async def add_coin_record(self, record: WalletCoinRecord) -> None:
        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.coin.name().hex(),
                record.confirmed_block_index,
                record.spent_block_index,
                int(record.spent),
                int(record.coinbase),
                str(record.coin.puzzle_hash.hex()),
                str(record.coin.parent_coin_info.hex()),
                record.coin.amount,
                record.wallet_type.value,
                record.wallet_id,
            ),
        )
        await cursor.close()
        await self.db_connection.commit()

        self.coin_record_cache[record.coin.name().hex()] = record
        if len(self.coin_record_cache) > self.cache_size:
            while len(self.coin_record_cache) > self.cache_size:
                first_in = list(self.coin_record_cache.keys())[0]
                del self.coin_record_cache[first_in]

    # Update coin_record to be spent in DB
    async def set_spent(self, coin_name: bytes32, index: uint32):
        current: Optional[WalletCoinRecord] = await self.get_coin_record(coin_name)
        if current is None:
            return
        spent: WalletCoinRecord = WalletCoinRecord(
            current.coin,
            current.confirmed_block_index,
            index,
            True,
            current.coinbase,
            current.wallet_type,
            current.wallet_id,
        )

        await self.add_coin_record(spent)

    async def get_coin_record(self, coin_name: bytes32) -> Optional[WalletCoinRecord]:
        """ Returns CoinRecord with specified coin id. """
        if coin_name.hex() in self.coin_record_cache:
            return self.coin_record_cache[coin_name.hex()]
        cursor = await self.db_connection.execute(
            "SELECT * from coin_record WHERE coin_name=?", (coin_name.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            coin = Coin(
                bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
            )
            return WalletCoinRecord(
                coin, row[1], row[2], row[3], row[4], WalletType(row[8]), row[9]
            )
        return None

    async def get_coin_records_by_spent(
        self, spent: bool, spend_before_height: Optional[uint32] = None
    ) -> Set[WalletCoinRecord]:
        """ Returns set of CoinRecords that have not been spent yet. """
        coins = set()
        if spend_before_height:
            cursor = await self.db_connection.execute(
                "SELECT * from coin_record WHERE spent=? OR spent_index>=?",
                (int(spent), spend_before_height),
            )
        else:
            cursor = await self.db_connection.execute(
                "SELECT * from coin_record WHERE spent=?", (int(spent),)
            )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            coin = Coin(
                bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
            )
            coins.add(
                WalletCoinRecord(
                    coin, row[1], row[2], row[3], row[4], WalletType(row[8]), row[9]
                )
            )
        return coins

    async def get_coin_records_by_spent_and_wallet(
        self, spent: bool, wallet_id: int
    ) -> Set[WalletCoinRecord]:
        """ Returns set of CoinRecords that have not been spent yet. """
        coins = set()

        cursor = await self.db_connection.execute(
            "SELECT * from coin_record WHERE spent=? and wallet_id=?",
            (int(spent), wallet_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            coin = Coin(
                bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
            )
            coins.add(
                WalletCoinRecord(
                    coin, row[1], row[2], row[3], row[4], WalletType(row[8]), row[9]
                )
            )
        return coins

    async def get_spendable_for_index(
        self, index: uint32, wallet_id: int
    ) -> Set[WalletCoinRecord]:
        """ Returns set of CoinRecords that have been confirmed before index height. """
        coins = set()
        print("index,", index, "walelt id", wallet_id)

        cursor_coinbase_coins = await self.db_connection.execute(
            "SELECT * from coin_record WHERE spent=? and confirmed_index<=? and wallet_id=? and coinbase=?",
            (0, int(index), wallet_id, 1),
        )

        coinbase_rows = await cursor_coinbase_coins.fetchall()
        await cursor_coinbase_coins.close()

        cursor_regular_coins = await self.db_connection.execute(
            "SELECT * from coin_record WHERE spent=? and wallet_id=? and coinbase=?",
            (0, wallet_id, 0,),
        )

        regular_rows = await cursor_regular_coins.fetchall()
        await cursor_regular_coins.close()

        for row in coinbase_rows:
            coin = Coin(
                bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
            )
            coins.add(
                WalletCoinRecord(
                    coin, row[1], row[2], row[3], row[4], WalletType(row[8]), row[9]
                )
            )

        for row in regular_rows:
            coin = Coin(
                bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
            )
            coins.add(
                WalletCoinRecord(
                    coin, row[1], row[2], row[3], row[4], WalletType(row[8]), row[9]
                )
            )

        return coins

    async def get_unspent_coins(self) -> Dict[bytes32, Coin]:
        """ Returns a dictionary of all unspent coins. """
        result: Dict[bytes32, Coin] = {}
        unspent_coin_records: Set[
            WalletCoinRecord
        ] = await self.get_coin_records_by_spent(False)

        for record in unspent_coin_records:
            result[record.name()] = record.coin

        return result

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(
        self, puzzle_hash: bytes32
    ) -> List[WalletCoinRecord]:
        coins = set()
        cursor = await self.db_connection.execute(
            "SELECT * from coin_record WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            coin = Coin(
                bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
            )
            coins.add(
                WalletCoinRecord(
                    coin, row[1], row[2], row[3], row[4], WalletType(row[8]), row[9]
                )
            )
        return list(coins)

    async def get_coin_record_by_coin_id(
        self, coin_id: bytes32
    ) -> Optional[WalletCoinRecord]:
        cursor = await self.db_connection.execute(
            "SELECT * from coin_record WHERE coin_name=?", (coin_id.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None

        coin = Coin(
            bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
        )
        coin_record = WalletCoinRecord(
            coin, row[1], row[2], row[3], row[4], WalletType(row[8]), row[9]
        )
        return coin_record

    async def rollback_lca_to_block(self, block_index):
        # Update memory cache
        delete_queue: bytes32 = []
        for coin_name, coin_record in self.coin_record_cache.items():
            if coin_record.spent_block_index > block_index:
                new_record = WalletCoinRecord(
                    coin_record.coin,
                    coin_record.confirmed_block_index,
                    coin_record.spent_block_index,
                    False,
                    coin_record.coinbase,
                    coin_record.wallet_type,
                    coin_record.wallet_id,
                )
                self.coin_record_cache[coin_record.coin.name().hex()] = new_record
            if coin_record.confirmed_block_index > block_index:
                delete_queue.append(coin_name)

        for coin_name in delete_queue:
            del self.coin_record_cache[coin_name]

        # Delete from storage
        c1 = await self.db_connection.execute(
            "DELETE FROM coin_record WHERE confirmed_index>?", (block_index,)
        )
        await c1.close()
        c2 = await self.db_connection.execute(
            "UPDATE coin_record SET spent_index = 0, spent = 0 WHERE spent_index>?",
            (block_index,),
        )
        await c2.close()
        await self.remove_blocks_from_path(block_index)
        await self.db_connection.commit()

    async def get_lca_path(self) -> Dict[bytes32, BlockRecord]:
        """
        Returns block records representing the blockchain from the genesis
        block up to the LCA (least common ancestor). Note that the DB also
        contains many blocks not on this path, due to reorgs.
        """
        cursor = await self.db_connection.execute(
            "SELECT * from block_records WHERE in_lca_path=1"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        hash_to_br: Dict = {}
        max_height = -1
        for row in rows:
            br = BlockRecord.from_bytes(row[3])
            hash_to_br[bytes.fromhex(row[0])] = br
            assert row[0] == br.header_hash.hex()
            assert row[1] == br.height
            if br.height > max_height:
                max_height = br.height
        # Makes sure there's exactly one block per height
        assert max_height == len(rows) - 1
        return hash_to_br

    async def add_block_record(self, block_record: BlockRecord, in_lca_path: bool):
        cursor = await self.db_connection.execute(
            "INSERT OR REPLACE INTO block_records VALUES(?, ?, ?, ?)",
            (
                block_record.header_hash.hex(),
                block_record.height,
                in_lca_path,
                bytes(block_record),
            ),
        )
        await cursor.close()
        await self.db_connection.commit()

    async def get_block_record(self, header_hash: bytes32) -> BlockRecord:
        cursor = await self.db_connection.execute(
            "SELECT * from block_records WHERE header_hash=?", (header_hash.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return BlockRecord.from_bytes(row[1])

    async def add_block_to_path(self, header_hash: bytes32) -> None:
        cursor = await self.db_connection.execute(
            "UPDATE block_records SET in_lca_path=1 WHERE header_hash=?",
            (header_hash.hex(),),
        )
        await cursor.close()
        await self.db_connection.commit()

    async def remove_blocks_from_path(self, from_height: uint32) -> None:
        """
        When rolling back the LCA, sets in_lca_path to 0 for blocks over the given
        height. This is used during reorgs to rollback the current lca.
        """
        cursor = await self.db_connection.execute(
            "UPDATE block_records SET in_lca_path=0 WHERE height>?", (from_height,),
        )
        await cursor.close()
        await self.db_connection.commit()
