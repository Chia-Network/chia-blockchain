from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, AsyncIterator, List, cast

from chia.util.action_scope import ActionScope
from chia.wallet.transaction_record import TransactionRecord

if TYPE_CHECKING:  # avoid circular import
    from chia.wallet.wallet_state_manager import WalletStateManager


@dataclass
class WalletSideEffects:
    transactions: List[TransactionRecord] = field(default_factory=list)

    def __bytes__(self) -> bytes:
        blob = b""
        for tx in self.transactions:
            tx_bytes = bytes(tx)
            blob += len(tx_bytes).to_bytes(4, "big") + tx_bytes
        return blob

    @classmethod
    def from_bytes(cls, blob: bytes) -> WalletSideEffects:
        instance = cls()
        while blob != b"":
            len_prefix = int.from_bytes(blob[:4], "big")
            blob = blob[4:]
            instance.transactions.append(TransactionRecord.from_bytes(blob[:len_prefix]))
            blob = blob[len_prefix:]

        return instance


@dataclass
class WalletActionScope(ActionScope[WalletSideEffects]):
    @classmethod
    @contextlib.asynccontextmanager
    async def new(
        cls,
        wallet_state_manager: WalletStateManager,
        push: bool = False,
        merge_spends: bool = True,
    ) -> AsyncIterator[WalletActionScope]:
        async with cls.new_scope(WalletSideEffects) as self:
            self = cast(WalletActionScope, self)
            yield self

        if push:
            self.side_effects.transactions = await wallet_state_manager.add_pending_transactions(
                self.side_effects.transactions, merge_spends=merge_spends
            )
