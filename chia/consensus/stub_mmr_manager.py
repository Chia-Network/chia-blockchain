from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

if TYPE_CHECKING:
    from chia.consensus.blockchain_interface import MMRManagerProtocol


class StubMMRManager:
    """
    Stub MMR manager for test mocks that cannot compute full MMR roots.
    Used in tests where MMR validation may be skipped or not relevant.
    """

    _protocol_check: ClassVar[MMRManagerProtocol] = cast("StubMMRManager", None)

    def get_mmr_root_for_block(
        self,
        prev_header_hash: bytes32 | None,
        new_sp_index: int,
        starts_new_slot: bool,
        blocks: Any,
        fork_height: uint32 | None = None,
    ) -> bytes32 | None:
        # Return empty bytes for test contexts
        return None

    def get_current_mmr_root(self) -> bytes32 | None:
        return None

    def add_block_to_mmr(self, header_hash: bytes32, prev_hash: bytes32, height: uint32) -> None:
        # No-op for stub manager
        pass

    def rollback_to_height(self, target_height: int, blocks: Any) -> None:
        # No-op for stub manager
        pass

    def copy(self) -> MMRManagerProtocol:
        # Return a new instance (stateless)
        return StubMMRManager()
