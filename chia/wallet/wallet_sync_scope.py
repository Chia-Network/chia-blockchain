from __future__ import annotations

import contextlib
import pickle  # noqa: S403
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self, cast, final

from chia_rs.sized_ints import uint32

from chia.util.action_scope import ActionScope
from chia.wallet.transaction_record import TransactionRecord

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager


@dataclass(frozen=True, kw_only=True)
class WebSocketEvent:
    name: str
    wallet_id: uint32 | None = None
    data: dict[str, Any] | None = None


@dataclass
class SyncSideEffects:
    websocket_events: list[WebSocketEvent] = field(default_factory=list)

    def __bytes__(self) -> bytes:
        serializable_websocket_events = []
        for event in self.websocket_events:
            if event.data is not None and "transaction" in event.data:
                event.data["transaction"] = bytes(event.data["transaction"])
            serializable_websocket_events.append(event)
        return pickle.dumps(serializable_websocket_events)

    @classmethod
    def from_bytes(cls, blob: bytes) -> Self:
        loaded_websocket_events = pickle.loads(blob)  # noqa: S301
        deserialized_websocket_events = []
        for event in loaded_websocket_events:
            if event.data is not None and "transaction" in event.data:
                event.data["transaction"] = TransactionRecord.from_bytes(event.data["transaction"])
            deserialized_websocket_events.append(event)
        return cls(websocket_events=deserialized_websocket_events)


@final
@dataclass(frozen=True, kw_only=True)
class WalletSyncConfig:
    pass


class WalletSyncScope(ActionScope[SyncSideEffects, WalletSyncConfig]):
    pass


@contextlib.asynccontextmanager
async def new_wallet_sync_scope(wallet_state_manager: WalletStateManager) -> AsyncIterator[WalletSyncScope]:
    async with WalletSyncScope.new_scope(SyncSideEffects, WalletSyncConfig()) as self:
        self = cast(WalletSyncScope, self)
        try:
            yield self
        except Exception:
            raise

    wallet_state_manager.commit_sync_scope(self)
