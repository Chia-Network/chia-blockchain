from __future__ import annotations

# import dataclasses
from secrets import token_bytes

import pytest

from chia._tests.util.db_connection import DBConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.util.ints import uint32, uint64

# from chia.wallet.dao_wallet.dao_wallet import DAOInfo, DAOWallet
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.singleton import create_singleton_puzzle
from chia.wallet.singleton_record import SingletonRecord
from chia.wallet.wallet_singleton_store import WalletSingletonStore


def get_record(wallet_id: uint32 = uint32(2)) -> SingletonRecord:
    launcher_id = bytes32(token_bytes(32))
    inner_puz = Program.to(1)
    inner_puz_hash = inner_puz.get_tree_hash()
    parent_puz = create_singleton_puzzle(inner_puz, launcher_id)
    parent_puz_hash = parent_puz.get_tree_hash()
    parent_coin = Coin(launcher_id, parent_puz_hash, uint64(1))
    inner_sol = Program.to([[51, inner_puz_hash, 1]])
    lineage_proof = LineageProof(launcher_id, inner_puz.get_tree_hash(), uint64(1))
    parent_sol = Program.to([lineage_proof.to_program(), 1, inner_sol])
    parent_coinspend = make_spend(parent_coin, parent_puz, parent_sol)
    pending = True
    removed_height = 0
    custom_data = "{'key': 'value'}"
    record = SingletonRecord(
        coin=parent_coin,
        singleton_id=launcher_id,
        wallet_id=wallet_id,
        parent_coinspend=parent_coinspend,
        inner_puzzle_hash=inner_puz_hash,
        pending=pending,
        removed_height=removed_height,
        lineage_proof=lineage_proof,
        custom_data=custom_data,
    )
    return record


class TestSingletonStore:
    @pytest.mark.anyio
    async def test_singleton_insert(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletSingletonStore.create(wrapper)
            record = get_record()
            await db.save_singleton(record)
            records_by_wallet = await db.get_records_by_wallet_id(record.wallet_id)
            assert records_by_wallet[0] == record
            record_by_coin_id = await db.get_records_by_coin_id(record.coin.name())
            assert record_by_coin_id[0] == record
            records_by_singleton_id = await db.get_records_by_singleton_id(record.singleton_id)
            assert records_by_singleton_id[0] == record
            # update pending
            await db.update_pending_transaction(record.coin.name(), False)
            record_to_check = (await db.get_records_by_coin_id(record.coin.name()))[0]
            assert record_to_check.pending is False
            assert record_to_check.custom_data == "{'key': 'value'}"

    @pytest.mark.anyio
    async def test_singleton_add_spend(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletSingletonStore.create(wrapper)
            record = get_record()
            child_coin = Coin(record.coin.name(), record.coin.puzzle_hash, uint64(1))
            parent_coinspend = record.parent_coinspend

            # test add spend
            await db.add_spend(uint32(2), parent_coinspend, uint32(10))
            record_by_id = (await db.get_records_by_coin_id(child_coin.name()))[0]
            assert record_by_id

            # Test adding a non-singleton will fail
            inner_puz = Program.to(1)
            inner_puz_hash = inner_puz.get_tree_hash()
            bad_coin = Coin(record.singleton_id, inner_puz_hash, uint64(1))
            inner_sol = Program.to([[51, inner_puz_hash, 1]])
            bad_coinspend = make_spend(bad_coin, inner_puz, inner_sol)
            with pytest.raises(RuntimeError) as e_info:
                await db.add_spend(uint32(2), bad_coinspend, uint32(10))
            assert e_info.value.args[0] == "Coin to add is not a valid singleton"

    @pytest.mark.anyio
    async def test_singleton_remove(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletSingletonStore.create(wrapper)
            record_1 = get_record()
            record_2 = get_record()
            await db.save_singleton(record_1)
            await db.save_singleton(record_2)
            resp_1 = await db.delete_singleton_by_coin_id(record_1.coin.name(), uint32(1))
            assert resp_1
            resp_2 = await db.delete_singleton_by_singleton_id(record_2.singleton_id, uint32(1))
            assert resp_2
            record = (await db.get_records_by_coin_id(record_1.coin.name()))[0]
            assert record.removed_height == 1
            record = (await db.get_records_by_coin_id(record_2.coin.name()))[0]
            assert record.removed_height == 1
            # delete a non-existing coin id
            fake_id = bytes32(b"x" * 32)
            resp_3 = await db.delete_singleton_by_coin_id(fake_id, uint32(10))
            assert not resp_3
            # delete a non-existing singleton id
            resp_4 = await db.delete_singleton_by_singleton_id(fake_id, uint32(10))
            assert not resp_4

    @pytest.mark.anyio
    async def test_singleton_delete_wallet(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletSingletonStore.create(wrapper)
            for i in range(1, 5):
                wallet_id = uint32(i)
                for _ in range(5):
                    record = get_record(wallet_id)
                    await db.save_singleton(record)
                assert not (await db.is_empty(wallet_id))

            for j in range(1, 5):
                wallet_id = uint32(j)
                start_count = await db.count()
                await db.delete_wallet(wallet_id)
                assert (await db.count(wallet_id)) == 0
                assert await db.is_empty(wallet_id)
                end_count = await db.count()
                assert end_count == start_count - 5

            assert await db.is_empty()

    @pytest.mark.anyio
    async def test_singleton_reorg(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletSingletonStore.create(wrapper)
            record = get_record()
            # save the singleton
            await db.save_singleton(record)
            # delete it at block 10
            await db.delete_singleton_by_coin_id(record.coin.name(), uint32(10))
            record_by_id = (await db.get_records_by_coin_id(record.coin.name()))[0]
            assert record_by_id.removed_height == 10
            # rollback
            await db.rollback(5, uint32(2))
            reorged_record_by_id = await db.get_records_by_coin_id(record.coin.name())
            assert not reorged_record_by_id
