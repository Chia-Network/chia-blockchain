
from __future__ import annotations

import pytest
from secrets import token_bytes

from chia.types.blockchain_format.coin import Coin
from chia.types.coin_spend import CoinSpend
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.dao_wallet.dao_wallet import DAOWallet, DAOInfo
from chia.wallet.wallet_singleton_store import WalletSingletonStore
from chia.wallet.singleton import create_fullpuz, get_singleton_id_from_puzzle
from chia.wallet.singleton_record import SingletonRecord
from tests.util.db_connection import DBConnection


class TestSingletonStore:
    @pytest.mark.asyncio
    async def test_singleton_insert(self) -> None:
        async with DBConnection(1) as wrapper:
            db = await WalletSingletonStore.create(wrapper)
            launcher_id = bytes32(token_bytes(32))
            inner_puz = Program.to(1)
            inner_puz_hash = inner_puz.get_tree_hash()
            parent_puz = create_fullpuz(inner_puz, launcher_id)

            parent_puz_hash = parent_puz.get_tree_hash()
            parent_coin = Coin(launcher_id, parent_puz_hash, 1)
            inner_sol = Program.to([[51, parent_puz_hash, 1]])
            lineage_proof = LineageProof(launcher_id, inner_puz.get_tree_hash(), 1)
            parent_sol = Program.to([lineage_proof.to_program(), 1, inner_sol])
            parent_coinspend = CoinSpend(parent_coin, parent_puz, parent_sol)
            child_coin = Coin(parent_coin.name(), parent_puz_hash, 1)
            wallet_id = 2
            pending = True
            removed_height = 3
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
                custom_data=custom_data
            )

            await db.save_singleton(record)

            spends = await db.get_spends_for_wallet(2)
        breakpoint()
