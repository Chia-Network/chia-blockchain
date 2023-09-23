from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List

import pytest

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo
from chia.wallet.wallet_nft_store import WalletNftStore
from tests.util.db_connection import DBConnection


def get_dummy_nft(random_: random.Random) -> NFTCoinInfo:
    return NFTCoinInfo(
        bytes32.random(random_),
        Coin(bytes32.random(random_), bytes32.random(random_), uint64(1)),
        LineageProof(bytes32.random(random_), bytes32.random(random_), uint64(1)),
        Program.to(["A Test puzzle"]),
        uint32(1),
    )


@dataclass
class DummyNFTs:
    seeded_random: random.Random
    nfts_per_wallet: Dict[uint32, List[NFTCoinInfo]] = field(default_factory=dict)

    def generate(self, wallet_id: int, count: int) -> None:
        nfts = self.nfts_per_wallet.setdefault(uint32(wallet_id), [])
        for _ in range(count):
            nfts.append(get_dummy_nft(random_=self.seeded_random))


class TestNftStore:
    @pytest.mark.asyncio
    async def test_nft_insert(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletNftStore.create(wrapper)
            a_bytes32 = bytes32.fromhex("09287c75377c63fd6a3a4d6658abed03e9a521e0436b1f83cdf4af99341ce8f1")
            b_bytes32 = bytes32.fromhex("09287c75377c63fd6a3a4d6658abed03e9a521e0436b1f83cdf4af99341ce8f2")
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
            nft2 = NFTCoinInfo(
                b_bytes32,
                Coin(b_bytes32, b_bytes32, uint64(1)),
                LineageProof(a_bytes32, a_bytes32, uint64(1)),
                puzzle,
                uint32(1),
                None,
                uint32(10),
            )
            assert await db.is_empty()
            # Test save
            await db.save_nft(uint32(1), a_bytes32, nft)
            assert not await db.is_empty()
            await db.save_nft(uint32(1), a_bytes32, nft)  # test for duplicates
            await db.save_nft(uint32(1), b_bytes32, nft2)
            # Test get nft
            assert await db.count() == 2
            assert nft == (await db.get_nft_list(wallet_id=uint32(1)))[0]
            assert nft == (await db.get_nft_list())[0]
            assert nft == (await db.get_nft_list(did_id=a_bytes32))[0]
            assert nft == (await db.get_nft_list(wallet_id=uint32(1), did_id=a_bytes32))[0]
            assert nft == await db.get_nft_by_id(a_bytes32)

            # test get nft list pagination
            assert not (await db.get_nft_list(wallet_id=uint32(1), start_index=0, count=0))
            assert nft == (await db.get_nft_list(wallet_id=uint32(1), start_index=0, count=1))[0]
            assert 1 == len(await db.get_nft_list(wallet_id=uint32(1), start_index=0, count=1))
            assert 2 == len(await db.get_nft_list(wallet_id=uint32(1), start_index=0, count=5))
            assert nft2 == (await db.get_nft_list(wallet_id=uint32(1), start_index=0, count=2))[1]
            assert nft2 == (await db.get_nft_list(wallet_id=uint32(1), start_index=1, count=1))[0]
            assert 0 == len(await db.get_nft_list(wallet_id=uint32(1), start_index=2, count=1))

            assert nft == (await db.get_nft_by_coin_id(nft.coin.name()))
            assert await db.exists(nft.coin.name())
            # negative tests
            assert (await db.get_nft_by_coin_id(bytes32(b"0" * 32))) is None
            assert not await db.exists(bytes32(b"0" * 32))

    @pytest.mark.asyncio
    async def test_nft_remove(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletNftStore.create(wrapper)
            a_bytes32 = bytes32.fromhex("09287c75377c63fd6a3a4d6658abed03e9a521e0436b1f83cdf4af99341ce8f1")
            puzzle = Program.to(["A Test puzzle"])
            coin = Coin(a_bytes32, a_bytes32, uint64(1))
            nft = NFTCoinInfo(
                a_bytes32,
                coin,
                LineageProof(a_bytes32, a_bytes32, uint64(1)),
                puzzle,
                uint32(1),
                a_bytes32,
                uint32(10),
            )
            # Test save
            await db.save_nft(uint32(1), a_bytes32, nft)
            assert not await db.is_empty()
            # Test delete by nft id
            await db.delete_nft_by_nft_id(a_bytes32, uint32(11))
            assert await db.get_nft_by_id(a_bytes32) is None
            assert await db.is_empty(wallet_id=uint32(1))

            # Test delete by coin id
            await db.save_nft(uint32(1), a_bytes32, nft)
            assert not await db.delete_nft_by_coin_id(a_bytes32, uint32(11))
            assert await db.delete_nft_by_coin_id(coin.name(), uint32(11))
            assert not await db.delete_nft_by_coin_id(a_bytes32, uint32(11))
            assert not await db.exists(a_bytes32)

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
            assert not (await db.get_nft_by_coin_id(nft_id_1))
            assert not await db.exists(coin_id_2)

            await db.rollback_to_block(-1)
            assert await db.count(wallet_id=uint32(1)) == 0
            assert await db.is_empty(wallet_id=uint32(1))


@pytest.mark.asyncio
async def test_delete_wallet(seeded_random: random.Random) -> None:
    dummy_nfts = DummyNFTs(seeded_random=seeded_random)
    for i in range(5):
        dummy_nfts.generate(i, i * 5)
    async with DBConnection(1) as wrapper:
        db = await WalletNftStore.create(wrapper)
        # Add the nfts per wallet and verify them
        for wallet_id, nfts in dummy_nfts.nfts_per_wallet.items():
            for nft in nfts:
                await db.save_nft(wallet_id, None, nft)
            assert await db.count(wallet_id) == len(nfts)
        # Remove one wallet after the other and verify before and after each
        for wallet_id, nfts in dummy_nfts.nfts_per_wallet.items():
            # Assert the length again here to make sure the previous removals did not affect other wallet_ids
            assert await db.count(wallet_id) == len(nfts)
            await db.delete_wallet(wallet_id)
            assert await db.count(wallet_id) == 0

        assert await db.is_empty()
