from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, AsyncIterator, List, Optional, cast

from chia.types.spend_bundle import SpendBundle
from chia.util.action_scope import ActionScope
from chia.wallet.signer_protocol import SigningResponse
from chia.wallet.transaction_record import TransactionRecord

if TYPE_CHECKING:
    # Avoid a circular import here
    from chia.wallet.wallet_state_manager import WalletStateManager


@dataclass
class WalletSideEffects:
    transactions: List[TransactionRecord] = field(default_factory=list)
    signing_responses: List[SigningResponse] = field(default_factory=list)
    extra_spends: List[SpendBundle] = field(default_factory=list)

    def __bytes__(self) -> bytes:
        blob = b""
        blob += len(self.transactions).to_bytes(4, "big")
        for tx in self.transactions:
            tx_bytes = bytes(tx)
            blob += len(tx_bytes).to_bytes(4, "big") + tx_bytes
        blob += len(self.signing_responses).to_bytes(4, "big")
        for sr in self.signing_responses:
            sr_bytes = bytes(sr)
            blob += len(sr_bytes).to_bytes(4, "big") + sr_bytes
        blob += len(self.extra_spends).to_bytes(4, "big")
        for sb in self.extra_spends:
            sb_bytes = bytes(sb)
            blob += len(sb_bytes).to_bytes(4, "big") + sb_bytes
        return blob

    @classmethod
    def from_bytes(cls, blob: bytes) -> WalletSideEffects:
        instance = cls()
        while blob != b"":
            tx_len_prefix = int.from_bytes(blob[:4], "big")
            blob = blob[4:]
            for _ in range(0, tx_len_prefix):
                len_prefix = int.from_bytes(blob[:4], "big")
                blob = blob[4:]
                instance.transactions.append(TransactionRecord.from_bytes(blob[:len_prefix]))
                blob = blob[len_prefix:]
            sr_len_prefix = int.from_bytes(blob[:4], "big")
            blob = blob[4:]
            for _ in range(0, sr_len_prefix):
                len_prefix = int.from_bytes(blob[:4], "big")
                blob = blob[4:]
                instance.signing_responses.append(SigningResponse.from_bytes(blob[:len_prefix]))
                blob = blob[len_prefix:]
            sb_len_prefix = int.from_bytes(blob[:4], "big")
            blob = blob[4:]
            for _ in range(0, sb_len_prefix):
                len_prefix = int.from_bytes(blob[:4], "big")
                blob = blob[4:]
                instance.extra_spends.append(SpendBundle.from_bytes(blob[:len_prefix]))
                blob = blob[len_prefix:]

        return instance


WalletActionScope = ActionScope[WalletSideEffects]


@contextlib.asynccontextmanager
async def new_wallet_action_scope(
    wallet_state_manager: WalletStateManager,
    push: bool = False,
    merge_spends: bool = True,
    sign: Optional[bool] = None,
    additional_signing_responses: List[SigningResponse] = [],
    extra_spends: List[SpendBundle] = [],
) -> AsyncIterator[WalletActionScope]:
    async with ActionScope.new_scope(WalletSideEffects) as self:
        self = cast(WalletActionScope, self)
        async with self.use() as interface:
            interface.side_effects.signing_responses = additional_signing_responses.copy()
            interface.side_effects.extra_spends = extra_spends.copy()

        yield self

    self.side_effects.transactions = await wallet_state_manager.add_pending_transactions(
        self.side_effects.transactions,
        push=push,
        merge_spends=merge_spends,
        sign=sign,
        additional_signing_responses=self.side_effects.signing_responses,
        extra_spends=self.side_effects.extra_spends,
    )
