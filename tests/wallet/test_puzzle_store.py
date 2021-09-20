import asyncio
from pathlib import Path
from secrets import token_bytes

import aiosqlite
import pytest
from blspy import AugSchemeMPL

from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_puzzle_store import WalletPuzzleStore


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestPuzzleStore:
    @pytest.mark.asyncio
    async def test_puzzle_store(self):
        db_filename = Path("puzzle_store_test.db")

        if db_filename.exists():
            db_filename.unlink()

        con = await aiosqlite.connect(db_filename)
        wrapper = DBWrapper(con)
        db = await WalletPuzzleStore.create(wrapper)
        try:
            derivation_recs = []
            # wallet_types = [t for t in WalletType]
            [t for t in WalletType]

            for i in range(1000):
                derivation_recs.append(
                    DerivationRecord(
                        uint32(i),
                        token_bytes(32),
                        AugSchemeMPL.key_gen(token_bytes(32)).get_g1(),
                        WalletType.STANDARD_WALLET,
                        uint32(1),
                        False,
                    )
                )
                derivation_recs.append(
                    DerivationRecord(
                        uint32(i),
                        token_bytes(32),
                        AugSchemeMPL.key_gen(token_bytes(32)).get_g1(),
                        WalletType.RATE_LIMITED,
                        uint32(2),
                        False,
                    )
                )
            assert await db.puzzle_hash_exists(derivation_recs[0].puzzle_hash) is False
            assert await db.index_for_pubkey(derivation_recs[0].pubkey) is None
            assert await db.index_for_puzzle_hash(derivation_recs[2].puzzle_hash) is None
            assert await db.wallet_info_for_puzzle_hash(derivation_recs[2].puzzle_hash) is None
            assert len((await db.get_all_puzzle_hashes())) == 0
            assert await db.get_last_derivation_path() is None
            assert await db.get_unused_derivation_path() is None
            assert await db.get_derivation_record(0, 2, False) is None

            await db.add_derivation_paths(derivation_recs)

            assert await db.puzzle_hash_exists(derivation_recs[0].puzzle_hash) is True

            phs_1 = [derivation_recs[0].puzzle_hash]
            phs_2 = [32 * bytes([1]), derivation_recs[0].puzzle_hash]
            phs_3 = [derivation_recs[0].puzzle_hash, 32 * bytes([1])]
            phs_4 = [32 * bytes([1]), 32 * bytes([2])]
            phs_5 = []
            assert await db.one_of_puzzle_hashes_exists(phs_1) is True
            assert await db.one_of_puzzle_hashes_exists(phs_2) is True
            assert await db.one_of_puzzle_hashes_exists(phs_3) is True
            assert await db.one_of_puzzle_hashes_exists(phs_4) is False
            assert await db.one_of_puzzle_hashes_exists(phs_5) is False

            assert await db.index_for_pubkey(derivation_recs[4].pubkey) == 2
            assert await db.index_for_puzzle_hash(derivation_recs[2].puzzle_hash) == 1
            assert await db.wallet_info_for_puzzle_hash(derivation_recs[2].puzzle_hash) == (
                derivation_recs[2].wallet_id,
                derivation_recs[2].wallet_type,
            )
            assert len((await db.get_all_puzzle_hashes())) == 2000
            assert await db.get_last_derivation_path() == 999
            assert await db.get_unused_derivation_path() == 0
            assert await db.get_derivation_record(0, 2, False) == derivation_recs[1]

            # Indeces up to 250
            await db.set_used_up_to(249)

            assert await db.get_unused_derivation_path() == 250

        except Exception as e:
            print(e, type(e))
            await db._clear_database()
            await db.close()
            db_filename.unlink()
            raise e

        await db._clear_database()
        await db.close()
        db_filename.unlink()
