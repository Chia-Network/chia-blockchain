import asyncio
from pathlib import Path
import aiosqlite
import pytest

from chia.util.db_wrapper import DBWrapper
from chia.wallet.util.wallet_types import WalletType

from chia.wallet.wallet_user_store import WalletUserStore


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletUserStore:
    @pytest.mark.asyncio
    async def test_store(self):
        db_filename = Path("wallet_user_store_test.db")

        if db_filename.exists():
            db_filename.unlink()

        db_connection = await aiosqlite.connect(db_filename)
        db_wrapper = DBWrapper(db_connection)
        store = await WalletUserStore.create(db_wrapper)
        try:
            await store.init_wallet()
            assert (await store.get_last_wallet()).id == 1
            wallet = await store.create_wallet("CAT_WALLET", WalletType.CAT, "abc")
            assert wallet is not None
            assert (await store.get_last_wallet()).id == 2
            wallet = await store.create_wallet("CAT_WALLET", WalletType.CAT, "abc")
            wallet = await store.create_wallet("CAT_WALLET", WalletType.CAT, "abc")
            wallet = await store.create_wallet("CAT_WALLET", WalletType.CAT, "abc")
            assert (await store.get_last_wallet()).id == 5

            print(await store.get_all_wallet_info_entries())
            for i in range(2, 6):
                await store.delete_wallet(i, in_transaction=False)

            print(await store.get_all_wallet_info_entries())
            assert (await store.get_last_wallet()).id == 1
            wallet = await store.create_wallet("CAT_WALLET", WalletType.CAT, "abc")
            # Due to autoincrement, we don't reuse IDs
            assert (await store.get_last_wallet()).id == 6
            assert wallet.id == 6

            assert (await store.get_wallet_by_id(7)) is None
            assert (await store.get_wallet_by_id(6)) == wallet
            assert store.get_last_wallet() == wallet

        finally:
            await db_connection.close()
            db_filename.unlink()
