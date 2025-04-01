from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from chia_rs.sized_ints import uint32

from chia.wallet.derivation_record import DerivationRecord

if TYPE_CHECKING:
    # avoiding a circular import
    from chia.wallet.wallet_state_manager import WalletStateManager


@dataclasses.dataclass
class CreateMorePuzzleHashesResult:
    derivation_paths: list[DerivationRecord]
    mark_existing_as_used: bool
    unused: int
    new_unhardened_keys: bool
    last_index: int

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
            wallet_state_manager.state_changed("new_derivation_index", data_object={"index": self.last_index - 1})
        # By default, we'll mark previously generated unused puzzle hashes as used if we have new paths
        if self.mark_existing_as_used and self.unused > 0 and self.new_unhardened_keys:
            wallet_state_manager.log.info(f"Updating last used derivation index: {self.unused - 1}")
            await wallet_state_manager.puzzle_store.set_used_up_to(uint32(self.unused - 1))


@dataclasses.dataclass
class GetUnusedDerivationRecordResult:
    record: DerivationRecord
    create_more_puzzle_hashes_result: CreateMorePuzzleHashesResult

    async def commit(self, wallet_state_manager: WalletStateManager) -> None:
        await self.create_more_puzzle_hashes_result.commit(wallet_state_manager)
        await wallet_state_manager.puzzle_store.set_used_up_to(self.record.index)
