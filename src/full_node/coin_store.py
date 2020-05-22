from typing import Dict, Optional, List
import aiosqlite
from src.types.full_block import FullBlock
from src.types.coin import Coin
from src.types.coin_record import CoinRecord
from src.types.sized_bytes import bytes32
from src.types.header import Header
from src.util.ints import uint32


class DiffStore:
    header: Header
    diffs: Dict[bytes32, CoinRecord]

    @staticmethod
    async def create(header: Header, diffs: Dict[bytes32, CoinRecord]):
        self = DiffStore()
        self.header = header
        self.diffs = diffs
        return self


class CoinStore:
    """
    This object handles CoinRecords in DB.
    Coins from genesis to LCA are stored on disk db, coins from lca to head are stored in DiffStore object for each tip.
    When blockchain notifies UnspentStore of new LCA, LCA is added to the disk db,
    DiffStores are updated/recreated. (managed by blockchain.py)
    """

    coin_record_db: aiosqlite.Connection
    lca_coin_records: Dict[str, CoinRecord]
    head_diffs: Dict[bytes32, DiffStore]
    cache_size: uint32

    @classmethod
    async def create(
        cls, connection: aiosqlite.Connection, cache_size: uint32 = uint32(600000)
    ):
        self = cls()

        self.cache_size = cache_size
        self.coin_record_db = connection
        await self.coin_record_db.execute(
            (
                "CREATE TABLE IF NOT EXISTS coin_record("
                "coin_name text PRIMARY KEY,"
                " confirmed_index bigint,"
                " spent_index bigint,"
                " spent int,"
                " coinbase int,"
                " puzzle_hash text,"
                " coin_parent text,"
                " amount bigint)"
            )
        )

        # Useful for reorg lookups
        await self.coin_record_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_confirmed_index on coin_record(confirmed_index)"
        )

        await self.coin_record_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent_index on coin_record(spent_index)"
        )

        await self.coin_record_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent on coin_record(spent)"
        )

        await self.coin_record_db.execute(
            "CREATE INDEX IF NOT EXISTS coin_spent on coin_record(puzzle_hash)"
        )

        await self.coin_record_db.commit()
        self.lca_coin_records = dict()
        self.head_diffs = dict()
        return self

    async def add_lcas(self, blocks: List[FullBlock]):
        for block in blocks:
            await self.new_lca(block)

    async def new_lca(self, block: FullBlock):
        removals, additions = await block.tx_removals_and_additions()

        for coin in additions:
            record: CoinRecord = CoinRecord(coin, block.height, uint32(0), False, False)
            await self.add_coin_record(record)

        for coin_name in removals:
            await self.set_spent(coin_name, block.height)

        coinbase: CoinRecord = CoinRecord(
            block.header.data.coinbase, block.height, uint32(0), False, True
        )
        fees_coin: CoinRecord = CoinRecord(
            block.header.data.fees_coin, block.height, uint32(0), False, True
        )

        await self.add_coin_record(coinbase)
        await self.add_coin_record(fees_coin)

    def nuke_diffs(self):
        self.head_diffs.clear()

    # Received new tip, just update diffs
    async def new_heads(self, blocks: List[FullBlock]):
        last: FullBlock = blocks[-1]
        diff_store: DiffStore = await DiffStore.create(last.header, dict())

        block: FullBlock
        for block in blocks:
            removals, additions = await block.tx_removals_and_additions()
            await self.add_diffs(removals, additions, block, diff_store)

        self.head_diffs[last.header_hash] = diff_store

    async def add_diffs(
        self,
        removals: List[bytes32],
        additions: List[Coin],
        block: FullBlock,
        diff_store: DiffStore,
    ):

        for coin in additions:
            added: CoinRecord = CoinRecord(coin, block.height, 0, 0, 0)  # type: ignore # noqa
            diff_store.diffs[added.name.hex()] = added

        coinbase: CoinRecord = CoinRecord(block.header.data.coinbase, block.height, 0, 0, 1)  # type: ignore # noqa
        diff_store.diffs[coinbase.name.hex()] = coinbase
        fees_coin: CoinRecord = CoinRecord(block.header.data.fees_coin, block.height, 0, 0, 1)  # type: ignore # noqa
        diff_store.diffs[fees_coin.name.hex()] = fees_coin

        for coin_name in removals:
            removed: Optional[CoinRecord] = None
            if coin_name.hex() in diff_store.diffs:
                removed = diff_store.diffs[coin_name.hex()]
            if removed is None:
                removed = await self.get_coin_record(coin_name)
            if removed is None:
                raise Exception
            spent = CoinRecord(
                removed.coin,
                removed.confirmed_block_index,
                block.height,
                True,
                removed.coinbase,
            )  # type: ignore # noqa
            diff_store.diffs[spent.name.hex()] = spent

    # Store CoinRecord in DB and ram cache
    async def add_coin_record(self, record: CoinRecord) -> None:
        cursor = await self.coin_record_db.execute(
            "INSERT OR REPLACE INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.coin.name().hex(),
                record.confirmed_block_index,
                record.spent_block_index,
                int(record.spent),
                int(record.coinbase),
                str(record.coin.puzzle_hash.hex()),
                str(record.coin.parent_coin_info.hex()),
                record.coin.amount,
            ),
        )
        await cursor.close()
        await self.coin_record_db.commit()
        self.lca_coin_records[record.coin.name().hex()] = record
        if len(self.lca_coin_records) > self.cache_size:
            while len(self.lca_coin_records) > self.cache_size:
                first_in = list(self.lca_coin_records.keys())[0]
                del self.lca_coin_records[first_in]

    # Update coin_record to be spent in DB
    async def set_spent(self, coin_name: bytes32, index: uint32):
        current: Optional[CoinRecord] = await self.get_coin_record(coin_name)
        if current is None:
            return
        spent: CoinRecord = CoinRecord(
            current.coin, current.confirmed_block_index, index, True, current.coinbase,
        )  # type: ignore # noqa
        await self.add_coin_record(spent)

    # Checks DB and DiffStores for CoinRecord with coin_name and returns it
    async def get_coin_record(
        self, coin_name: bytes32, header: Header = None
    ) -> Optional[CoinRecord]:
        if header is not None and header.header_hash in self.head_diffs:
            diff_store = self.head_diffs[header.header_hash]
            if coin_name.hex() in diff_store.diffs:
                return diff_store.diffs[coin_name.hex()]
        if coin_name.hex() in self.lca_coin_records:
            return self.lca_coin_records[coin_name.hex()]
        cursor = await self.coin_record_db.execute(
            "SELECT * from coin_record WHERE coin_name=?", (coin_name.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            coin = Coin(
                bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
            )
            return CoinRecord(coin, row[1], row[2], row[3], row[4])
        return None

    # Checks DB and DiffStores for CoinRecords with puzzle_hash and returns them
    async def get_coin_records_by_puzzle_hash(
        self, puzzle_hash: bytes32, header: Header = None
    ) -> List[CoinRecord]:
        coins = set()
        if header is not None and header.header_hash in self.head_diffs:
            diff_store = self.head_diffs[header.header_hash]
            for _, record in diff_store.diffs.items():
                if record.coin.puzzle_hash == puzzle_hash:
                    coins.add(record)
        cursor = await self.coin_record_db.execute(
            "SELECT * from coin_record WHERE puzzle_hash=?", (puzzle_hash.hex(),)
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            coin = Coin(
                bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), row[7]
            )
            coins.add(CoinRecord(coin, row[1], row[2], row[3], row[4]))
        return list(coins)

    async def rollback_lca_to_block(self, block_index):
        # Update memory cache
        delete_queue: bytes32 = []
        for coin_name, coin_record in self.lca_coin_records.items():
            if coin_record.spent_block_index > block_index:
                new_record = CoinRecord(
                    coin_record.coin,
                    coin_record.confirmed_block_index,
                    coin_record.spent_block_index,
                    False,
                    coin_record.coinbase,
                )
                self.lca_coin_records[coin_record.coin.name().hex()] = new_record
            if coin_record.confirmed_block_index > block_index:
                delete_queue.append(coin_name)

        for coin_name in delete_queue:
            del self.lca_coin_records[coin_name]

        # Delete from storage
        c1 = await self.coin_record_db.execute(
            "DELETE FROM coin_record WHERE confirmed_index>?", (block_index,)
        )
        await c1.close()
        c2 = await self.coin_record_db.execute(
            "UPDATE coin_record SET spent_index = 0, spent = 0 WHERE spent_index>?",
            (block_index,),
        )
        await c2.close()
        await self.coin_record_db.commit()
