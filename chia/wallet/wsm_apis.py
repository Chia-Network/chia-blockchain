from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from chia_rs.sized_ints import uint32

from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.wallet_sync_scope import WebSocketEvent

if TYPE_CHECKING:
    # avoiding a circular import
    from chia.wallet.wallet_state_manager import WalletStateManager


@dataclasses.dataclass
class CreateMorePuzzleHashesResult:
    derivation_paths: list[DerivationRecord]
    unused: int  # The first unused puzzle hash
    new_unhardened_keys: bool
    last_index: int  # The index we derived up to

    async def commit(self, wallet_state_manager: WalletStateManager) -> None:
        if len(self.derivation_paths) > 0:
            await wallet_state_manager.puzzle_store.add_derivation_paths(self.derivation_paths)
            await wallet_state_manager.wallet_node.new_peak_queue.subscribe_to_puzzle_hashes(
                [
                    record.puzzle_hash
                    for record in self.derivation_paths
                    if record.wallet_id == wallet_state_manager.main_wallet.id()
                ]
            )
        if self.new_unhardened_keys:
            wallet_state_manager._dispatch_websocket_event(
                WebSocketEvent(name="new_derivation_index", data={"index": self.last_index - 1})
            )


@dataclasses.dataclass
class GetUnusedDerivationRecordResult:
    record: DerivationRecord
    create_more_puzzle_hashes_result: CreateMorePuzzleHashesResult
    used_indices: list[uint32] = dataclasses.field(default_factory=list)

    async def commit(self, wallet_state_manager: WalletStateManager) -> None:
        await self.create_more_puzzle_hashes_result.commit(wallet_state_manager)
        for index in self.used_indices:
            await wallet_state_manager.puzzle_store.mark_used(index)
