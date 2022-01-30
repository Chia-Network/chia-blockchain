from pathlib import Path
import aiosqlite
import pytest

from chia.util.db_wrapper import DBWrapper
from chia.wallet.util.wallet_types import WalletType

from chia.wallet.wallet_user_store import WalletUserStore


@pytest.mark.asyncio
async def test_store():
    db_filename = Path("wallet_user_store_test.db")

    if db_filename.exists():
        db_filename.unlink()

    db_connection = await aiosqlite.connect(db_filename)
    db_wrapper = DBWrapper(db_connection)
    store = await WalletUserStore.create(db_wrapper)
    try:
        await store.init_wallet()
        wallet = None
        for i in range(1, 5):
            assert (await store.get_last_wallet()).id == i
            wallet = await store.create_wallet("CAT_WALLET", WalletType.CAT, "abc")
            assert wallet.id == i + 1
        assert wallet.id == 5

        for i in range(2, 6):
            await store.delete_wallet(i, in_transaction=False)

        assert (await store.get_last_wallet()).id == 1
        wallet = await store.create_wallet("CAT_WALLET", WalletType.CAT, "abc")
        # Due to autoincrement, we don't reuse IDs
        assert (await store.get_last_wallet()).id == 6
        assert wallet.id == 6

        assert (await store.get_wallet_by_id(7)) is None
        assert (await store.get_wallet_by_id(6)) == wallet
        assert await store.get_last_wallet() == wallet

    finally:
        await db_connection.close()
        db_filename.unlink()
