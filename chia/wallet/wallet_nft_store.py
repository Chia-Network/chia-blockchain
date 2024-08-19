from __future__ import annotations

import json
import logging
from sqlite3 import Row
from typing import List, Optional, Type, TypeVar, Union

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.ints import uint32
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet.nft_info import DEFAULT_STATUS, IN_TRANSACTION_STATUS, NFTCoinInfo

log = logging.getLogger(__name__)
_T_WalletNftStore = TypeVar("_T_WalletNftStore", bound="WalletNftStore")
REMOVE_BUFF_BLOCKS = 1000
NFT_COIN_INFO_COLUMNS = "nft_id, coin, lineage_proof, mint_height, status, full_puzzle, latest_height, minter_did"


def _to_nft_coin_info(row: Row) -> NFTCoinInfo:
    # nft_id, coin, lineage_proof, mint_height, status, full_puzzle, latest_height, minter_did
    return NFTCoinInfo(
        bytes32.from_hexstr(row[0]),
        Coin.from_json_dict(json.loads(row[1])),
        None if row[2] is None else LineageProof.from_json_dict(json.loads(row[2])),
        Program.from_bytes(row[5]),
        uint32(row[3]),
        None if row[7] is None else bytes32.from_hexstr(row[7]),
        uint32(row[6]) if row[6] is not None else uint32(0),
        row[4] == IN_TRANSACTION_STATUS,
    )


class WalletNftStore:
    """
    WalletNftStore keeps track of all user created NFTs and necessary smart-contract data
    """

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls: Type[_T_WalletNftStore], db_wrapper: DBWrapper2) -> _T_WalletNftStore:
        self = cls()
        self.db_wrapper = db_wrapper
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS users_nfts("
                " nft_id text PRIMARY KEY,"
                " nft_coin_id text,"
                " wallet_id int,"
                " did_id text,"
                " coin text,"
                " lineage_proof text,"
                " mint_height bigint,"
                " status text,"
                " full_puzzle blob)"
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS nft_coin_id on users_nfts(nft_coin_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS nft_wallet_id on users_nfts(wallet_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS nft_did_id on users_nfts(did_id)")
            try:
                # Add your new column on the top, otherwise it will not be created.
                await conn.execute("ALTER TABLE users_nfts ADD COLUMN minter_did text")
                # These are patched columns for resolving reorg issue
                await conn.execute("ALTER TABLE users_nfts ADD COLUMN removed_height bigint")
                await conn.execute("ALTER TABLE users_nfts ADD COLUMN latest_height bigint")
                await conn.execute("CREATE INDEX IF NOT EXISTS removed_nft_height on users_nfts(removed_height)")
                await conn.execute("CREATE INDEX IF NOT EXISTS latest_nft_height on users_nfts(latest_height)")
            except Exception:
                pass

        return self

    async def delete_nft_by_nft_id(self, nft_id: bytes32, height: uint32) -> bool:
        """Tries to mark a given NFT as deleted at specific height

        This is due to how re-org works
        Returns `True` if NFT was found and marked deleted or `False` if not."""
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Remove NFT in the users_nfts table
            cursor = await conn.execute(
                "UPDATE users_nfts SET removed_height=? WHERE nft_id=?", (int(height), nft_id.hex())
            )
            return cursor.rowcount > 0

    async def delete_nft_by_coin_id(self, coin_id: bytes32, height: uint32) -> bool:
        """Tries to mark a given NFT as deleted at specific height

        This is due to how re-org works
        Returns `True` if NFT was found and marked deleted or `False` if not."""
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Remove NFT in the users_nfts table
            cursor = await conn.execute(
                "UPDATE users_nfts SET removed_height=? WHERE nft_coin_id=?", (int(height), coin_id.hex())
            )
            if cursor.rowcount > 0:
                log.info("Deleted NFT with coin id: %s", coin_id.hex())
                return True
            log.warning("Couldn't find NFT with coin id to delete: %s", coin_id)
            return False

    async def update_pending_transaction(self, nft_coin_id: bytes32, pending_transaction: bool) -> bool:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            c = await conn.execute(
                "UPDATE users_nfts SET status=? WHERE nft_coin_id = ?",
                (IN_TRANSACTION_STATUS if pending_transaction else DEFAULT_STATUS, nft_coin_id.hex()),
            )
            return c.rowcount > 0

    async def save_nft(self, wallet_id: uint32, did_id: Optional[bytes32], nft_coin_info: NFTCoinInfo) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            columns = (
                "nft_id, nft_coin_id, wallet_id, did_id, coin, lineage_proof, mint_height, status, full_puzzle, "
                "minter_did, removed_height, latest_height"
            )
            await conn.execute(
                f"INSERT or REPLACE INTO users_nfts ({columns}) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    nft_coin_info.nft_id.hex(),
                    nft_coin_info.coin.name().hex(),
                    int(wallet_id),
                    did_id.hex() if did_id else None,
                    json.dumps(nft_coin_info.coin.to_json_dict()),
                    (
                        json.dumps(nft_coin_info.lineage_proof.to_json_dict())
                        if nft_coin_info.lineage_proof is not None
                        else None
                    ),
                    int(nft_coin_info.mint_height),
                    IN_TRANSACTION_STATUS if nft_coin_info.pending_transaction else DEFAULT_STATUS,
                    bytes(nft_coin_info.full_puzzle),
                    None if nft_coin_info.minter_did is None else nft_coin_info.minter_did.hex(),
                    None,
                    int(nft_coin_info.latest_height),
                ),
            )
            # Rotate the old removed NFTs, they are not possible to be reorged
            await conn.execute(
                "DELETE FROM users_nfts WHERE removed_height is not NULL and removed_height<?",
                (int(nft_coin_info.latest_height) - REMOVE_BUFF_BLOCKS,),
            )

    async def count(self, wallet_id: Optional[uint32] = None, did_id: Optional[bytes32] = None) -> int:
        sql = "SELECT COUNT(nft_id) FROM users_nfts WHERE removed_height is NULL"
        params: List[Union[uint32, bytes32]] = []
        if wallet_id is not None:
            sql += " AND wallet_id=?"
            params.append(wallet_id)
        if did_id is not None:
            sql += " AND did_id=?"
            params.append(did_id)
        async with self.db_wrapper.reader_no_transaction() as conn:
            count_row = await execute_fetchone(conn, sql, params)
            if count_row:
                return int(count_row[0])
        return -1

    async def is_empty(self, wallet_id: Optional[uint32] = None) -> bool:
        sql = "SELECT 1 FROM users_nfts WHERE removed_height is NULL"
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

    async def get_nft_list(
        self,
        wallet_id: Optional[uint32] = None,
        did_id: Optional[bytes32] = None,
        start_index: int = 0,
        count: int = 50,
    ) -> List[NFTCoinInfo]:
        try:
            start_index = int(start_index)
        except ValueError:
            start_index = 0
        try:
            count = int(count)
        except ValueError:
            count = 50

        sql: str = f"SELECT {NFT_COIN_INFO_COLUMNS} from users_nfts WHERE"
        if wallet_id is not None and did_id is None:
            sql += f" wallet_id={wallet_id}"
        if wallet_id is None and did_id is not None:
            sql += f" did_id='{did_id.hex()}'"
        if wallet_id is not None and did_id is not None:
            sql += f" did_id='{did_id.hex()}' and wallet_id={wallet_id}"
        if wallet_id is not None or did_id is not None:
            sql += " and"
        sql += " removed_height is NULL"
        sql += " LIMIT ? OFFSET ?"
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(sql, (count, start_index))

        return [
            NFTCoinInfo(
                bytes32.from_hexstr(row[0]),
                Coin.from_json_dict(json.loads(row[1])),
                None if row[2] is None else LineageProof.from_json_dict(json.loads(row[2])),
                Program.from_bytes(row[5]),
                uint32(row[3]),
                None if row[7] is None else bytes32.from_hexstr(row[7]),
                uint32(row[6]) if row[6] is not None else uint32(0),
                row[4] == IN_TRANSACTION_STATUS,
            )
            for row in rows
        ]

    async def exists(self, coin_id: bytes32) -> bool:
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await execute_fetchone(
                conn,
                "SELECT EXISTS(SELECT nft_id"
                " from users_nfts WHERE removed_height is NULL and nft_coin_id=? LIMIT 1)",
                (coin_id.hex(),),
            )
            return True if rows and rows[0] == 1 else False

    async def get_nft_by_coin_id(self, nft_coin_id: bytes32) -> Optional[NFTCoinInfo]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(
                f"SELECT {NFT_COIN_INFO_COLUMNS} from users_nfts WHERE removed_height is NULL and nft_coin_id = ?",
                (nft_coin_id.hex(),),
            )
        rows = list(rows)
        if len(rows) == 1:
            return _to_nft_coin_info(rows[0])
        elif len(rows) == 2:
            raise ValueError("Can only return one NFT, but found > 1 from given coin ids")
        return None

    async def get_nft_by_id(self, nft_id: bytes32, wallet_id: Optional[uint32] = None) -> Optional[NFTCoinInfo]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            sql = f"SELECT {NFT_COIN_INFO_COLUMNS} from users_nfts WHERE removed_height is NULL and nft_id=?"
            params: List[Union[uint32, str]] = [nft_id.hex()]
            if wallet_id:
                sql += " and wallet_id=?"
                params.append(wallet_id)
            row = await execute_fetchone(
                conn,
                sql,
                params,
            )

        if row is None:
            return None

        return _to_nft_coin_info(row)

    async def rollback_to_block(self, height: int) -> bool:
        """
        Rolls back the blockchain to block_index. All coins confirmed after this point are removed.
        All coins spent after this point are set to unspent. Can be -1 (rollback all)
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Remove reorged NFTs
            await conn.execute("DELETE FROM users_nfts WHERE latest_height>?", (height,))

            # Retrieve removed NFTs
            result = await conn.execute(
                "UPDATE users_nfts SET removed_height = null WHERE removed_height>?",
                (height,),
            )
            if result.rowcount > 0:
                return True
            return False

    async def delete_wallet(self, wallet_id: uint32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute("DELETE FROM users_nfts WHERE wallet_id=?", (wallet_id,))
            await cursor.close()
