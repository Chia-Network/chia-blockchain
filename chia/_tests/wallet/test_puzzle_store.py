from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List

import pytest
from chia_rs import AugSchemeMPL

from chia._tests.util.db_connection import DBConnection
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.util.wallet_types import WalletIdentifier, WalletType
from chia.wallet.wallet_puzzle_store import WalletPuzzleStore


def get_dummy_record(index: int, wallet_id: int, seeded_random: random.Random) -> DerivationRecord:
    return DerivationRecord(
        uint32(index),
        bytes32.random(seeded_random),
        AugSchemeMPL.key_gen(bytes32.random(seeded_random)).get_g1(),
        WalletType.STANDARD_WALLET,
        uint32(wallet_id),
        False,
    )


@dataclass
class DummyDerivationRecords:
    seeded_random: random.Random
    index_per_wallet: Dict[int, int] = field(default_factory=dict)
    records_per_wallet: Dict[int, List[DerivationRecord]] = field(default_factory=dict)

    def generate(self, wallet_id: int, count: int) -> None:
        records = self.records_per_wallet.setdefault(wallet_id, [])
        self.index_per_wallet.setdefault(wallet_id, 0)
        for _ in range(count):
            records.append(
                get_dummy_record(self.index_per_wallet[wallet_id], wallet_id, seeded_random=self.seeded_random)
            )
            self.index_per_wallet[wallet_id] += 1


@pytest.mark.anyio
async def test_puzzle_store(seeded_random: random.Random) -> None:
    async with DBConnection(1) as wrapper:
        db = await WalletPuzzleStore.create(wrapper)
        derivation_recs = []
        for i in range(1000):
            derivation_recs.append(
                DerivationRecord(
                    uint32(i),
                    bytes32.random(seeded_random),
                    AugSchemeMPL.key_gen(bytes32.random(seeded_random)).get_g1(),
                    WalletType.STANDARD_WALLET,
                    uint32(1),
                    False,
                )
            )
            derivation_recs.append(
                DerivationRecord(
                    uint32(i),
                    bytes32.random(seeded_random),
                    AugSchemeMPL.key_gen(bytes32.random(seeded_random)).get_g1(),
                    WalletType.CAT,
                    uint32(2),
                    False,
                )
            )
        assert await db.puzzle_hash_exists(derivation_recs[0].puzzle_hash) is False
        assert await db.index_for_pubkey(derivation_recs[0].pubkey) is None
        assert await db.index_for_puzzle_hash(derivation_recs[2].puzzle_hash) is None
        assert await db.get_wallet_identifier_for_puzzle_hash(derivation_recs[2].puzzle_hash) is None
        assert len(await db.get_all_puzzle_hashes()) == 0
        assert await db.get_last_derivation_path() is None
        assert await db.get_unused_derivation_path() is None
        assert await db.get_derivation_record(0, 2, False) is None

        await db.add_derivation_paths(derivation_recs)

        assert await db.puzzle_hash_exists(derivation_recs[0].puzzle_hash) is True

        assert await db.index_for_pubkey(derivation_recs[4].pubkey) == 2
        assert await db.index_for_puzzle_hash(derivation_recs[2].puzzle_hash) == 1
        assert await db.get_wallet_identifier_for_puzzle_hash(derivation_recs[2].puzzle_hash) == WalletIdentifier(
            derivation_recs[2].wallet_id,
            derivation_recs[2].wallet_type,
        )
        assert len(await db.get_all_puzzle_hashes()) == 2000
        assert await db.get_last_derivation_path() == 999
        assert await db.get_unused_derivation_path() == 0
        assert await db.get_derivation_record(0, 2, False) == derivation_recs[1]

        # Indeces up to 250
        await db.set_used_up_to(249)

        assert await db.get_unused_derivation_path() == 250


@pytest.mark.anyio
async def test_delete_wallet(seeded_random: random.Random) -> None:
    dummy_records = DummyDerivationRecords(seeded_random=seeded_random)
    for i in range(5):
        dummy_records.generate(i, i * 5)
    async with DBConnection(1) as wrapper:
        db = await WalletPuzzleStore.create(wrapper)
        # Add the records per wallet and verify them
        for wallet_id, records in dummy_records.records_per_wallet.items():
            await db.add_derivation_paths(records)
            for record in records:
                assert await db.get_derivation_record(record.index, record.wallet_id, record.hardened) == record
                assert await db.get_wallet_identifier_for_puzzle_hash(record.puzzle_hash) == WalletIdentifier(
                    record.wallet_id, record.wallet_type
                )
        # Remove one wallet after the other and verify before and after each
        for wallet_id, records in dummy_records.records_per_wallet.items():
            # Assert the existence again here to make sure the previous removals did not affect other wallet_ids
            for record in records:
                assert await db.get_derivation_record(record.index, record.wallet_id, record.hardened) == record
                assert await db.get_wallet_identifier_for_puzzle_hash(record.puzzle_hash) == WalletIdentifier(
                    record.wallet_id, record.wallet_type
                )
                assert await db.get_last_derivation_path_for_wallet(wallet_id) is not None
            # Remove the wallet_id and make sure its removed fully
            await db.delete_wallet(wallet_id)
            for record in records:
                assert await db.get_derivation_record(record.index, record.wallet_id, record.hardened) is None
                assert await db.get_wallet_identifier_for_puzzle_hash(record.puzzle_hash) is None
                assert await db.get_last_derivation_path_for_wallet(wallet_id) is None
        assert await db.get_last_derivation_path() is None
        assert db.last_derivation_index is None
        assert len(db.last_wallet_derivation_index) == 0
