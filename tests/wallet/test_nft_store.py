import pytest

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo
from chia.wallet.wallet_nft_store import WalletNftStore
from tests.util.db_connection import DBConnection


class TestNftStore:
    @pytest.mark.asyncio
    async def test_nft_store(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletNftStore.create(wrapper)
            a_bytes32 = bytes32.fromhex("09287c75377c63fd6a3a4d6658abed03e9a521e0436b1f83cdf4af99341ce8f1")
            puzzle = Program.to(["A Test puzzle"])
            nft = NFTCoinInfo(
                a_bytes32,
                Coin(a_bytes32, a_bytes32, uint64(1)),
                LineageProof(a_bytes32, a_bytes32, uint64(1)),
                puzzle,
                uint32(10),
            )
            # Test save
            await db.save_nft(uint32(1), a_bytes32, nft)
            # Test get nft
            assert nft == (await db.get_nft_list(wallet_id=uint32(1)))[0]
            assert nft == (await db.get_nft_list())[0]
            assert nft == (await db.get_nft_list(did_id=a_bytes32))[0]
            assert nft == (await db.get_nft_list(wallet_id=uint32(1), did_id=a_bytes32))[0]
            assert nft == await db.get_nft_by_id(a_bytes32)
            # Test delete
            await db.delete_nft(a_bytes32)
            assert await db.get_nft_by_id(a_bytes32) is None
