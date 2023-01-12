from __future__ import annotations

from secrets import token_bytes
from typing import Optional

import pytest
from clvm_tools import binutils

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.wallet_pool_store import WalletPoolStore
from tests.util.db_connection import DBConnection


def make_child_solution(coin_spend: CoinSpend, new_coin: Optional[Coin] = None) -> CoinSpend:
    new_puzzle_hash: bytes32 = bytes32(token_bytes(32))
    solution = "()"
    puzzle = f"(q . ((51 0x{new_puzzle_hash.hex()} 1)))"
    puzzle_prog = Program.to(binutils.assemble(puzzle))
    solution_prog = Program.to(binutils.assemble(solution))
    if new_coin is None:
        new_coin = coin_spend.additions()[0]
    sol: CoinSpend = CoinSpend(
        new_coin,
        SerializedProgram.from_program(puzzle_prog),
        SerializedProgram.from_program(solution_prog),
    )
    return sol


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
