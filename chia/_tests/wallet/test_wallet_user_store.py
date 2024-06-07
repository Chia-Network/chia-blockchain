from __future__ import annotations

import pytest

from chia._tests.util.db_connection import DBConnection
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_user_store import WalletUserStore


@pytest.mark.anyio
async def test_store() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletUserStore.create(db_wrapper)
        await store.init_wallet()
        wallet = None
        for i in range(1, 5):
            assert (await store.get_last_wallet()).id == i
            wallet = await store.create_wallet("CAT_WALLET", WalletType.CAT, "abc")
            assert wallet.id == i + 1
        assert wallet is not None
        assert wallet.id == 5

        for i in range(2, 6):
            await store.delete_wallet(i)

        assert (await store.get_last_wallet()).id == 1
        wallet = await store.create_wallet("CAT_WALLET", WalletType.CAT, "abc")
        # Due to autoincrement, we don't reuse IDs
        assert (await store.get_last_wallet()).id == 6
        assert wallet.id == 6

        assert (await store.get_wallet_by_id(7)) is None
        assert (await store.get_wallet_by_id(6)) == wallet
        assert await store.get_last_wallet() == wallet
