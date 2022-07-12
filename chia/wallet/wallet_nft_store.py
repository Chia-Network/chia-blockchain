import json
from typing import List, Optional, Type, TypeVar

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet.nft_info import DEFAULT_STATUS, IN_TRANSACTION_STATUS, NFTCoinInfo

_T_WalletNftStore = TypeVar("_T_WalletNftStore", bound="WalletNftStore")


class WalletNftStore:
    """
    WalletNftStore keeps track of all user created NFTs and necessary smart-contract data
    """

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls: Type[_T_WalletNftStore], db_wrapper: DBWrapper2) -> _T_WalletNftStore:
        self = cls()
        self.db_wrapper = db_wrapper
        async with self.db_wrapper.write_db() as conn:
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
        return self

    async def delete_nft(self, nft_id: bytes32) -> None:
        async with self.db_wrapper.write_db() as conn:
            await (await conn.execute(f"DELETE FROM users_nfts where nft_id='{nft_id.hex()}'")).close()

    async def save_nft(self, wallet_id: uint32, did_id: Optional[bytes32], nft_coin_info: NFTCoinInfo) -> None:
        async with self.db_wrapper.write_db() as conn:
            cursor = await conn.execute(
                "INSERT or REPLACE INTO users_nfts VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                ),
            )
            await cursor.close()

    async def get_nft_list(
        self, wallet_id: Optional[uint32] = None, did_id: Optional[bytes32] = None
    ) -> List[NFTCoinInfo]:
        sql: str = "SELECT nft_id, coin, lineage_proof, mint_height, status, full_puzzle from users_nfts"
        if wallet_id is not None and did_id is None:
            sql += f" where wallet_id={wallet_id}"
        if wallet_id is None and did_id is not None:
            sql += f" where did_id='{did_id.hex()}'"
        if wallet_id is not None and did_id is not None:
            sql += f" where did_id='{did_id.hex()}' and wallet_id={wallet_id}"

        async with self.db_wrapper.read_db() as conn:
            cursor = await conn.execute(sql)
            rows = await cursor.fetchall()
            await cursor.close()
        result = []

        for row in rows:
            result.append(
                NFTCoinInfo(
                    bytes32.from_hexstr(row[0]),
                    Coin.from_json_dict(json.loads(row[1])),
                    None if row[2] is None else LineageProof.from_json_dict(json.loads(row[2])),
                    Program.from_bytes(row[5]),
                    uint32(row[3]),
                    row[4] == IN_TRANSACTION_STATUS,
                )
            )
        return result

    async def get_nft_by_id(self, nft_id: bytes32) -> Optional[NFTCoinInfo]:
        async with self.db_wrapper.read_db() as conn:
            cursor = await conn.execute(
                "SELECT nft_id, coin, lineage_proof, mint_height, status, full_puzzle from users_nfts WHERE nft_id=?",
                (nft_id.hex(),),
            )
            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return NFTCoinInfo(
            bytes32.from_hexstr(row[0]),
            Coin.from_json_dict(json.loads(row[1])),
            None if row[2] is None else LineageProof.from_json_dict(json.loads(row[2])),
            Program.from_bytes(row[5]),
            uint32(row[3]),
            row[4] == IN_TRANSACTION_STATUS,
        )
