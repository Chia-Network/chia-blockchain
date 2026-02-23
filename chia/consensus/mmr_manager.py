from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.blockchain_interface import BlockRecordsProtocol

if TYPE_CHECKING:
    from chia.consensus.blockchain_interface import MMRManagerProtocol


class _ReadOnlyMMRManager:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[MMRManagerProtocol] = cast("_ReadOnlyMMRManager", None)

    _wrapped: MMRManagerProtocol

    def __init__(self, wrapped: MMRManagerProtocol) -> None:
        self._wrapped = wrapped

    def get_mmr_root_for_block(
        self,
        prev_header_hash: bytes32,
        new_sp_index: int,
        starts_new_slot: bool,
        blocks: BlockRecordsProtocol,
        fork_height: uint32 | None = None,
    ) -> bytes32 | None:
        return self._wrapped.get_mmr_root_for_block(
            prev_header_hash, new_sp_index, starts_new_slot, blocks, fork_height
        )

    def get_current_mmr_root(self) -> bytes32 | None:
        return self._wrapped.get_current_mmr_root()

    def add_block_to_mmr(self, header_hash: bytes32, prev_hash: bytes32, height: uint32) -> None:
        raise RuntimeError("read-only MMR manager does not allow mutation")

    def rollback_to_height(self, target_height: int, blocks: BlockRecordsProtocol) -> None:
        raise RuntimeError("read-only MMR manager does not allow mutation")

    def get_aggrtegate_from(self) -> uint32:
        return self._wrapped.get_aggrtegate_from()

    def copy(self) -> MMRManagerProtocol:
        return _ReadOnlyMMRManager(self._wrapped)
