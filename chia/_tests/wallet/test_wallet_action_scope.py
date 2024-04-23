from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import pytest

from chia._tests.cmds.wallet.test_consts import STD_TX
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_action_scope import WalletActionScope, WalletSideEffects


def test_back_and_forth_serialization() -> None:
    assert bytes(WalletSideEffects()) == b""
    assert WalletSideEffects.from_bytes(bytes(WalletSideEffects())) == WalletSideEffects()
    assert WalletSideEffects.from_bytes(bytes(WalletSideEffects([STD_TX]))) == WalletSideEffects([STD_TX])
    assert WalletSideEffects.from_bytes(bytes(WalletSideEffects([STD_TX, STD_TX]))) == WalletSideEffects(
        [STD_TX, STD_TX]
    )


@dataclass
class MockWalletStateManager:
    most_recent_call: Optional[Tuple[List[TransactionRecord], bool]] = None

    async def add_pending_transactions(
        self, txs: List[TransactionRecord], merge_spends: bool
    ) -> List[TransactionRecord]:
        self.most_recent_call = (txs, merge_spends)
        return txs


@pytest.mark.anyio
async def test_wallet_action_scope() -> None:
    wsm = MockWalletStateManager()
    async with WalletActionScope.new(wsm, push=True, merge_spends=False) as action_scope:  # type: ignore[arg-type]
        async with action_scope.use() as interface:
            interface.side_effects.transactions = [STD_TX]

        with pytest.raises(RuntimeError):
            action_scope.side_effects

    assert action_scope.side_effects.transactions == [STD_TX]
    assert wsm.most_recent_call == ([STD_TX], False)

    async with WalletActionScope.new(wsm, push=False, merge_spends=True) as action_scope:  # type: ignore[arg-type]
        async with action_scope.use() as interface:
            interface.side_effects.transactions = []

    assert action_scope.side_effects.transactions == []
    assert wsm.most_recent_call == ([STD_TX], False)
