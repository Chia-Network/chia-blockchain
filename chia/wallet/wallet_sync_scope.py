from __future__ import annotations

import contextlib
import pickle  # noqa: S403
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self, cast, final

from chia_rs.sized_ints import uint32

from chia.util.action_scope import ActionScope

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
        return pickle.dumps(self)

    @classmethod
    def from_bytes(cls, blob: bytes) -> Self:
        return cast(Self, pickle.loads(blob))  # noqa: S301


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
