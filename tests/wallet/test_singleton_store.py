from __future__ import annotations

# import dataclasses
from secrets import token_bytes

import pytest

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint32, uint64

# from chia.wallet.dao_wallet.dao_wallet import DAOInfo, DAOWallet
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.singleton import create_singleton_puzzle
from chia.wallet.singleton_record import SingletonRecord
from chia.wallet.wallet_singleton_store import WalletSingletonStore
from tests.util.db_connection import DBConnection


def get_record() -> SingletonRecord:
    launcher_id = bytes32(token_bytes(32))
    inner_puz = Program.to(1)
    inner_puz_hash = inner_puz.get_tree_hash()
    parent_puz = create_singleton_puzzle(inner_puz, launcher_id)
    parent_puz_hash = parent_puz.get_tree_hash()
    parent_coin = Coin(launcher_id, parent_puz_hash, 1)
    inner_sol = Program.to([[51, parent_puz_hash, 1]])
    lineage_proof = LineageProof(launcher_id, inner_puz.get_tree_hash(), uint64(1))
    parent_sol = Program.to([lineage_proof.to_program(), 1, inner_sol])
    parent_coinspend = CoinSpend(parent_coin, parent_puz, parent_sol)
    # child_coin = Coin(parent_coin.name(), parent_puz_hash, 1)
    wallet_id = uint32(2)
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
    @pytest.mark.asyncio
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
            # modify pending
            await db.update_pending_transaction(record.coin.name(), False)
            record_to_check = await db.get_records_by_coin_id(record.coin.name())
            assert record_to_check[0].pending is False

    @pytest.mark.asyncio
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
