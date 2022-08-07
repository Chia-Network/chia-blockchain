import json
from typing import List, Optional, Type, TypeVar

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.ints import uint32
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet.nft_info import DEFAULT_STATUS, IN_TRANSACTION_STATUS, NFTCoinInfo

_T_WalletNftStore = TypeVar("_T_WalletNftStore", bound="WalletNftStore")
REMOVE_BUFF_BLOCKS = 1000


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
                (
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
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS nft_coin_id on users_nfts(nft_coin_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS nft_wallet_id on users_nfts(wallet_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS nft_did_id on users_nfts(did_id)")
            try:
                # These are patched columns for resolving reorg issue
                await conn.execute("ALTER TABLE users_nfts ADD COLUMN removed_height bigint")
                await conn.execute("ALTER TABLE users_nfts ADD COLUMN latest_height bigint")
                await conn.execute("CREATE INDEX IF NOT EXISTS removed_nft_height on users_nfts(removed_height)")
                await conn.execute("CREATE INDEX IF NOT EXISTS latest_nft_height on users_nfts(latest_height)")
            except Exception:
                pass

        return self

    async def delete_nft(self, nft_id: bytes32, height: uint32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Remove NFT in the users_nfts table
            await (
                await conn.execute("UPDATE users_nfts SET removed_height=? WHERE nft_id=?", (int(height), nft_id.hex()))
            ).close()

    async def save_nft(self, wallet_id: uint32, did_id: Optional[bytes32], nft_coin_info: NFTCoinInfo) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT or REPLACE INTO users_nfts VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    nft_coin_info.nft_id.hex(),
                    nft_coin_info.coin.name().hex(),
                    int(wallet_id),
                    did_id.hex() if did_id else None,
                    json.dumps(nft_coin_info.coin.to_json_dict()),
                    json.dumps(nft_coin_info.lineage_proof.to_json_dict())
                    if nft_coin_info.lineage_proof is not None
                    else None,
                    int(nft_coin_info.mint_height),
                    IN_TRANSACTION_STATUS if nft_coin_info.pending_transaction else DEFAULT_STATUS,
                    bytes(nft_coin_info.full_puzzle),
                    None,
                    int(nft_coin_info.latest_height),
                ),
            )
            await cursor.close()
            # Rotate the old removed NFTs, they are not possible to be reorged
            await (
                await conn.execute(
                    "DELETE FROM users_nfts WHERE removed_height is not NULL and removed_height<?",
                    (int(nft_coin_info.latest_height) - REMOVE_BUFF_BLOCKS,),
                )
            ).close()

    async def get_nft_list(
        self, wallet_id: Optional[uint32] = None, did_id: Optional[bytes32] = None
    ) -> List[NFTCoinInfo]:
        sql: str = (
            "SELECT nft_id, coin, lineage_proof, mint_height, status, full_puzzle, latest_height"
            " from users_nfts WHERE"
        )
        if wallet_id is not None and did_id is None:
            sql += f" wallet_id={wallet_id}"
        if wallet_id is None and did_id is not None:
            sql += f" did_id='{did_id.hex()}'"
        if wallet_id is not None and did_id is not None:
            sql += f" did_id='{did_id.hex()}' and wallet_id={wallet_id}"
        if wallet_id is not None or did_id is not None:
            sql += " and"
        sql += " removed_height is NULL"
        async with self.db_wrapper.reader_no_transaction() as conn:
            rows = await conn.execute_fetchall(sql)

        return [
            NFTCoinInfo(
                bytes32.from_hexstr(row[0]),
                Coin.from_json_dict(json.loads(row[1])),
                None if row[2] is None else LineageProof.from_json_dict(json.loads(row[2])),
                Program.from_bytes(row[5]),
                uint32(row[3]),
                uint32(row[6]) if row[6] is not None else uint32(0),
                row[4] == IN_TRANSACTION_STATUS,
            )
            for row in rows
        ]

    async def get_nft_by_id(self, nft_id: bytes32) -> Optional[NFTCoinInfo]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(
                conn,
                "SELECT nft_id, coin, lineage_proof, mint_height, status, full_puzzle, latest_height"
                " from users_nfts WHERE removed_height is NULL and nft_id=?",
                (nft_id.hex(),),
            )

        if row is None:
            return None

        return NFTCoinInfo(
            bytes32.from_hexstr(row[0]),
            Coin.from_json_dict(json.loads(row[1])),
            None if row[2] is None else LineageProof.from_json_dict(json.loads(row[2])),
            Program.from_bytes(row[5]),
            uint32(row[3]),
            uint32(row[6]) if row[6] is not None else uint32(0),
            row[4] == IN_TRANSACTION_STATUS,
        )

    async def rollback_to_block(self, height: int) -> None:
        """
        Rolls back the blockchain to block_index. All coins confirmed after this point are removed.
        All coins spent after this point are set to unspent. Can be -1 (rollback all)
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            # Remove reorged NFTs
            await (await conn.execute("DELETE FROM users_nfts WHERE latest_height>?", (height,))).close()

            # Retrieve removed NFTs
            await (
                await conn.execute(
                    "UPDATE users_nfts SET removed_height = null WHERE removed_height>?",
                    (height,),
                )
            ).close()
