from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from chia_rs.sized_ints import uint32

from chia.util.streamable import Streamable, streamable
from chia.wallet.derivation_record import DerivationRecord, StreamableDerivationRecord

if TYPE_CHECKING:
    # avoiding a circular import
    from chia.wallet.wallet_state_manager import WalletStateManager


@streamable
@dataclasses.dataclass(frozen=True)
class StreamableCreateMorePuzzleHashesResult(Streamable):
    derivation_paths: list[StreamableDerivationRecord]
    mark_existing_as_used: bool
    unused: uint32
    new_unhardened_keys: bool
    last_index: uint32

    @classmethod
    def from_standard(cls, result: CreateMorePuzzleHashesResult) -> StreamableCreateMorePuzzleHashesResult:
        return cls(
            [StreamableDerivationRecord.from_standard(path) for path in result.derivation_paths],
            result.mark_existing_as_used,
            uint32(result.unused),
            result.new_unhardened_keys,
            uint32(result.last_index),
        )

    def to_standard(self) -> CreateMorePuzzleHashesResult:
        return CreateMorePuzzleHashesResult(
            [path.to_standard() for path in self.derivation_paths],
            self.mark_existing_as_used,
            self.unused,
            self.new_unhardened_keys,
            self.last_index,
        )


@dataclasses.dataclass
class CreateMorePuzzleHashesResult:
    derivation_paths: list[DerivationRecord]
    mark_existing_as_used: bool
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
            wallet_state_manager.state_changed("new_derivation_index", data_object={"index": self.last_index - 1})
        # By default, we'll mark previously generated unused puzzle hashes as used if we have new paths
        if self.mark_existing_as_used and self.unused > 0 and self.new_unhardened_keys:
            wallet_state_manager.log.info(f"Updating last used derivation index: {self.unused - 1}")
            await wallet_state_manager.puzzle_store.set_used_up_to(uint32(self.unused - 1))


@streamable
@dataclasses.dataclass(frozen=True)
class StreambleGetUnusedDerivationRecordResult(Streamable):
    record: StreamableDerivationRecord
    create_more_puzzle_hashes_result: StreamableCreateMorePuzzleHashesResult

    @classmethod
    def from_standard(cls, result: GetUnusedDerivationRecordResult) -> StreambleGetUnusedDerivationRecordResult:
        return cls(
            StreamableDerivationRecord.from_standard(result.record),
            StreamableCreateMorePuzzleHashesResult.from_standard(result.create_more_puzzle_hashes_result),
        )

    def to_standard(self) -> GetUnusedDerivationRecordResult:
        return GetUnusedDerivationRecordResult(
            self.record.to_standard(),
            self.create_more_puzzle_hashes_result.to_standard(),
        )


@dataclasses.dataclass
class GetUnusedDerivationRecordResult:
    record: DerivationRecord
    create_more_puzzle_hashes_result: CreateMorePuzzleHashesResult

    async def commit(self, wallet_state_manager: WalletStateManager) -> None:
        await self.create_more_puzzle_hashes_result.commit(wallet_state_manager)
        await wallet_state_manager.puzzle_store.set_used_up_to(self.record.index)
