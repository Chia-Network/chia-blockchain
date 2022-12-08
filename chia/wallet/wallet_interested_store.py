from __future__ import annotations

from typing import List, Optional, Tuple

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32


class WalletInterestedStore:
    """
    Stores coin ids that we are interested in receiving
    """

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, wrapper: DBWrapper2):
        self = cls()
        self.db_wrapper = wrapper

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS interested_coins(coin_name text PRIMARY KEY)")

            await conn.execute(
                "CREATE TABLE IF NOT EXISTS interested_puzzle_hashes(puzzle_hash text PRIMARY KEY, wallet_id integer)"
            )

            # Table for unknown CATs
            fields = "asset_id text PRIMARY KEY, name text, first_seen_height integer, sender_puzzle_hash text"
            await conn.execute(f"CREATE TABLE IF NOT EXISTS unacknowledged_asset_tokens({fields})")

        return self

    async def get_interested_coin_ids(self) -> List[bytes32]:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute("SELECT coin_name FROM interested_coins")
            rows_hex = await cursor.fetchall()
        return [bytes32(bytes.fromhex(row[0])) for row in rows_hex]

    async def add_interested_coin_id(self, coin_id: bytes32) -> None:

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute("INSERT OR REPLACE INTO interested_coins VALUES (?)", (coin_id.hex(),))
            await cursor.close()

    async def get_interested_puzzle_hashes(self) -> List[Tuple[bytes32, int]]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute("SELECT puzzle_hash, wallet_id FROM interested_puzzle_hashes")
            rows_hex = await cursor.fetchall()
        return [(bytes32(bytes.fromhex(row[0])), row[1]) for row in rows_hex]

    async def get_interested_puzzle_hash_wallet_id(self, puzzle_hash: bytes32) -> Optional[int]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT wallet_id FROM interested_puzzle_hashes WHERE puzzle_hash=?", (puzzle_hash.hex(),)
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return row[0]

    async def add_interested_puzzle_hash(self, puzzle_hash: bytes32, wallet_id: int) -> None:

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT OR REPLACE INTO interested_puzzle_hashes VALUES (?, ?)", (puzzle_hash.hex(), wallet_id)
            )
            await cursor.close()

    async def remove_interested_puzzle_hash(self, puzzle_hash: bytes32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "DELETE FROM interested_puzzle_hashes WHERE puzzle_hash=?", (puzzle_hash.hex(),)
            )
            await cursor.close()

    async def add_unacknowledged_token(
        self,
        asset_id: bytes32,
        name: str,
        first_seen_height: Optional[uint32],
        sender_puzzle_hash: bytes32,
    ) -> None:
        """
        Add an unacknowledged CAT to the database. It will only be inserted once at the first time.
        :param asset_id: CAT asset ID
        :param name: Name of the CAT, for now it will be unknown until we integrate the CAT name service
        :param first_seen_height: The block height of the wallet received this CAT in the first time
        :param sender_puzzle_hash: The puzzle hash of the sender
        :return: None
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT OR IGNORE INTO unacknowledged_asset_tokens VALUES (?, ?, ?, ?)",
                (
                    asset_id.hex(),
                    name,
                    first_seen_height if first_seen_height is not None else 0,
                    sender_puzzle_hash.hex(),
                ),
            )
            await cursor.close()

    async def get_unacknowledged_tokens(self) -> List:
        """
        Get a list of all unacknowledged CATs
        :return: A json style list of unacknowledged CATs
        """
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT asset_id, name, first_seen_height, sender_puzzle_hash FROM unacknowledged_asset_tokens"
            )
            cats = await cursor.fetchall()
        return [
            {"asset_id": cat[0], "name": cat[1], "first_seen_height": cat[2], "sender_puzzle_hash": cat[3]}
            for cat in cats
        ]
