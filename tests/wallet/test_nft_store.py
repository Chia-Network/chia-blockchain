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
    async def test_nft_insert(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletNftStore.create(wrapper)
            a_bytes32 = bytes32.fromhex("09287c75377c63fd6a3a4d6658abed03e9a521e0436b1f83cdf4af99341ce8f1")
            puzzle = Program.to(["A Test puzzle"])
            nft = NFTCoinInfo(
                a_bytes32,
                Coin(a_bytes32, a_bytes32, uint64(1)),
                LineageProof(a_bytes32, a_bytes32, uint64(1)),
                puzzle,
                uint32(1),
                None,
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

            assert nft == (await db.get_nft_by_coin_id(nft.coin.name()))
            assert nft == (await db.get_nft_by_coin_ids([nft.coin.name()]))
            assert await db.exists(nft.coin.name())

    @pytest.mark.asyncio
    async def test_nft_remove(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletNftStore.create(wrapper)
            a_bytes32 = bytes32.fromhex("09287c75377c63fd6a3a4d6658abed03e9a521e0436b1f83cdf4af99341ce8f1")
            puzzle = Program.to(["A Test puzzle"])
            nft = NFTCoinInfo(
                a_bytes32,
                Coin(a_bytes32, a_bytes32, uint64(1)),
                LineageProof(a_bytes32, a_bytes32, uint64(1)),
                puzzle,
                uint32(1),
                a_bytes32,
                uint32(10),
            )
            # Test save
            await db.save_nft(uint32(1), a_bytes32, nft)
            # Test delete
            await db.delete_nft_by_nft_id(a_bytes32, uint32(11))
            assert await db.get_nft_by_id(a_bytes32) is None

    @pytest.mark.asyncio
    async def test_nft_reorg(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletNftStore.create(wrapper)
            a_bytes32 = bytes32.fromhex("09287c75377c63fd6a3a4d6658abed03e9a521e0436b1f83cdf4af99341ce8f0")
            nft_id_1 = bytes32.fromhex("09287c75377c63fd6a3a4d6658abed03e9a521e0436b1f83cdf4af99341ce8f1")
            coin_id_1 = bytes32.fromhex("09287c75377c63fd6a3a4d6658abed03e9a521e0436b1f83cdf4af99341ce8f2")
            nft_id_2 = bytes32.fromhex("09287c75377c63fd6a3a4d6658abed03e9a521e0436b1f83cdf4af99341ce8f3")
            coin_id_2 = bytes32.fromhex("09287c75377c63fd6a3a4d6658abed03e9a521e0436b1f83cdf4af99341ce8f4")
            puzzle = Program.to(["A Test puzzle"])
            nft = NFTCoinInfo(
                nft_id_1,
                Coin(coin_id_1, coin_id_1, uint64(1)),
                LineageProof(coin_id_1, coin_id_1, uint64(1)),
                puzzle,
                uint32(1),
                a_bytes32,
                uint32(10),
            )
            # Test save
            await db.save_nft(uint32(1), nft_id_1, nft)
            # Test delete
            await db.delete_nft_by_nft_id(nft_id_1, uint32(11))
            assert await db.get_nft_by_id(nft_id_1) is None
            # Test reorg
            nft1 = NFTCoinInfo(
                nft_id_2,
                Coin(coin_id_2, coin_id_2, uint64(1)),
                LineageProof(coin_id_2, coin_id_2, uint64(1)),
                puzzle,
                uint32(1),
                a_bytes32,
                uint32(12),
            )
            await db.save_nft(uint32(1), nft_id_1, nft1)
            assert nft1 == (await db.get_nft_list(wallet_id=uint32(1)))[0]
            assert await db.rollback_to_block(10)
            assert nft == (await db.get_nft_list(wallet_id=uint32(1)))[0]

            assert not (await db.get_nft_by_coin_id(coin_id_2))
            assert not (await db.get_nft_by_coin_ids([nft_id_1]))
            assert not await db.exists(coin_id_2)
