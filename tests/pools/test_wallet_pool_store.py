from __future__ import annotations

from dataclasses import dataclass, field
from secrets import token_bytes
from typing import Dict, List, Optional

import pytest
from clvm_tools import binutils

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.util.ints import uint32, uint64
from chia.wallet.wallet_pool_store import WalletPoolStore
from tests.util.db_connection import DBConnection


def make_child_solution(coin_spend: Optional[CoinSpend], new_coin: Optional[Coin] = None) -> CoinSpend:
    new_puzzle_hash: bytes32 = bytes32(token_bytes(32))
    solution = "()"
    puzzle = f"(q . ((51 0x{new_puzzle_hash.hex()} 1)))"
    puzzle_prog = Program.to(binutils.assemble(puzzle))
    solution_prog = Program.to(binutils.assemble(solution))
    if new_coin is None:
        assert coin_spend is not None
        new_coin = compute_additions(coin_spend)[0]
    sol: CoinSpend = CoinSpend(
        new_coin,
        SerializedProgram.from_program(puzzle_prog),
        SerializedProgram.from_program(solution_prog),
    )
    return sol


async def assert_db_spends(store: WalletPoolStore, wallet_id: int, spends: List[CoinSpend]) -> None:
    db_spends = await store.get_spends_for_wallet(wallet_id)
    assert len(db_spends) == len(spends)
    for spend, (_, db_spend) in zip(spends, db_spends):
        assert spend == db_spend


@dataclass
class DummySpends:
    spends_per_wallet: Dict[int, List[CoinSpend]] = field(default_factory=dict)

    def generate(self, wallet_id: int, count: int) -> None:
        current = self.spends_per_wallet.setdefault(wallet_id, [])
        for _ in range(count):
            coin = None
            last_spend = None if len(current) == 0 else current[-1]
            if last_spend is None:
                coin = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            current.append(make_child_solution(last_spend, coin))


class TestWalletPoolStore:
    @pytest.mark.asyncio
    async def test_store(self):
        async with DBConnection(1) as db_wrapper:
            store = await WalletPoolStore.create(db_wrapper)

            try:
                async with db_wrapper.writer():
                    coin_0 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
                    coin_0_alt = Coin(token_bytes(32), token_bytes(32), uint64(12312))
                    solution_0: CoinSpend = make_child_solution(None, coin_0)
                    solution_0_alt: CoinSpend = make_child_solution(None, coin_0_alt)
                    solution_1: CoinSpend = make_child_solution(solution_0)

                    assert await store.get_spends_for_wallet(0) == []
                    assert await store.get_spends_for_wallet(1) == []

                    await store.add_spend(1, solution_1, 100)
                    assert await store.get_spends_for_wallet(1) == [(100, solution_1)]

                    # Idempotent
                    await store.add_spend(1, solution_1, 100)
                    assert await store.get_spends_for_wallet(1) == [(100, solution_1)]

                    with pytest.raises(ValueError):
                        await store.add_spend(1, solution_1, 101)

                    # Rebuild cache, no longer present
                    raise RuntimeError("abandon transaction")
            except Exception:
                pass

            assert await store.get_spends_for_wallet(1) == []

            await store.add_spend(1, solution_1, 100)
            assert await store.get_spends_for_wallet(1) == [(100, solution_1)]

            solution_1_alt: CoinSpend = make_child_solution(solution_0_alt)

            with pytest.raises(ValueError):
                await store.add_spend(1, solution_1_alt, 100)

            assert await store.get_spends_for_wallet(1) == [(100, solution_1)]

            solution_2: CoinSpend = make_child_solution(solution_1)
            await store.add_spend(1, solution_2, 100)
            solution_3: CoinSpend = make_child_solution(solution_2)
            await store.add_spend(1, solution_3, 100)
            solution_4: CoinSpend = make_child_solution(solution_3)

            with pytest.raises(ValueError):
                await store.add_spend(1, solution_4, 99)

            await store.add_spend(1, solution_4, 101)
            await store.rollback(101, 1)
            assert await store.get_spends_for_wallet(1) == [
                (100, solution_1),
                (100, solution_2),
                (100, solution_3),
                (101, solution_4),
            ]
            await store.rollback(100, 1)
            assert await store.get_spends_for_wallet(1) == [
                (100, solution_1),
                (100, solution_2),
                (100, solution_3),
            ]
            with pytest.raises(ValueError):
                await store.add_spend(1, solution_1, 105)

            await store.add_spend(1, solution_4, 105)
            solution_5: CoinSpend = make_child_solution(solution_4)
            await store.add_spend(1, solution_5, 105)
            await store.rollback(99, 1)
            assert await store.get_spends_for_wallet(1) == []


@pytest.mark.asyncio
async def test_delete_wallet() -> None:
    dummy_spends = DummySpends()
    for i in range(5):
        dummy_spends.generate(i, i * 5)
    async with DBConnection(1) as db_wrapper:
        store = await WalletPoolStore.create(db_wrapper)
        # Add the spends per wallet and verify them
        for wallet_id, spends in dummy_spends.spends_per_wallet.items():
            for i, spend in enumerate(spends):
                await store.add_spend(wallet_id, spend, uint32(i + wallet_id))
            await assert_db_spends(store, wallet_id, spends)
        # Remove one wallet after the other and verify before and after each
        for wallet_id, spends in dummy_spends.spends_per_wallet.items():
            # Assert the existence again here to make sure the previous removals did not affect other wallet_ids
            await assert_db_spends(store, wallet_id, spends)
            await store.delete_wallet(wallet_id)
            await assert_db_spends(store, wallet_id, [])
