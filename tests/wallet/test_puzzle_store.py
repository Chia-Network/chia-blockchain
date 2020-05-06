import asyncio
from secrets import token_bytes
from pathlib import Path
from typing import Any, Dict
import sqlite3
import random
import pytest
import aiosqlite
from blspy import PrivateKey
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.wallet.wallet_puzzle_store import WalletPuzzleStore
from src.wallet.derivation_record import DerivationRecord
from src.wallet.util.wallet_types import WalletType


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
        db = await WalletPuzzleStore.create(con)
        try:
            derivation_recs = []
            wallet_types = [t for t in WalletType]

            for i in range(1000):
                derivation_recs.append(
                    DerivationRecord(
                        uint32(i),
                        token_bytes(32),
                        PrivateKey.from_seed(token_bytes(5)).get_public_key(),
                        WalletType.STANDARD_WALLET,
                        uint32(1),
                    )
                )
                derivation_recs.append(
                    DerivationRecord(
                        uint32(i),
                        token_bytes(32),
                        PrivateKey.from_seed(token_bytes(5)).get_public_key(),
                        WalletType.RATE_LIMITED,
                        uint32(2),
                    )
                )
            assert await db.puzzle_hash_exists(derivation_recs[0].puzzle_hash) == False
            assert await db.index_for_pubkey(derivation_recs[0].pubkey) == None
            assert (
                await db.index_for_puzzle_hash(derivation_recs[2].puzzle_hash) == None
            )
            assert (
                await db.wallet_info_for_puzzle_hash(derivation_recs[2].puzzle_hash)
                == None
            )
            assert len((await db.get_all_puzzle_hashes())) == 0
            assert await db.get_last_derivation_path() == None
            assert await db.get_unused_derivation_path() == None
            assert await db.get_derivation_record(0, 2) == None

            await db.add_derivation_paths(derivation_recs)

            assert await db.puzzle_hash_exists(derivation_recs[0].puzzle_hash) == True
            assert await db.index_for_pubkey(derivation_recs[4].pubkey) == 2
            assert await db.index_for_puzzle_hash(derivation_recs[2].puzzle_hash) == 1
            assert await db.wallet_info_for_puzzle_hash(
                derivation_recs[2].puzzle_hash
            ) == (derivation_recs[2].wallet_id, derivation_recs[2].wallet_type)
            assert len((await db.get_all_puzzle_hashes())) == 2000
            assert await db.get_last_derivation_path() == 999
            assert await db.get_unused_derivation_path() == 0
            assert await db.get_derivation_record(0, 2) == derivation_recs[1]

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
