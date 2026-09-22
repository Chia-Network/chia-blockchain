from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

if TYPE_CHECKING:
    from chia.consensus.block_store_protocol import MMRState
    from chia.consensus.blockchain_interface import MMRManagerProtocol


class StubMMRManager:
    """
    Stub MMR manager for test mocks that cannot compute full MMR roots.
    Used in tests where MMR validation may be skipped or not relevant.
    """

    _protocol_check: ClassVar[MMRManagerProtocol] = cast("StubMMRManager", None)

    def get_mmr_root_for_block(
        self,
        prev_header_hash: bytes32,
        new_sp_index: int,
        starts_new_slot: bool,
        blocks: Any,
        fork_height: uint32 | None = None,
    ) -> bytes32 | None:
        # Return empty bytes for test contexts
        return None

    def compute_current_mmr_root(self) -> bytes32 | None:
        return None

    def register_block_commitment(self, header_hash: bytes32, coin_commitments_root: bytes32) -> None:
        # No-op for stub manager
        pass

    def add_block_to_mmr(self, header_hash: bytes32, prev_hash: bytes32, height: uint32) -> None:
        # No-op for stub manager
        pass

    def rollback_to_height(self, target_height: int, blocks: Any) -> None:
        # No-op for stub manager
        pass

    def get_aggrtegate_from(self) -> uint32:
        # Stub returns 0 (aggregate from genesis)
        return uint32(0)

    def copy(self) -> MMRManagerProtocol:
        # Return a new instance (stateless)
        return StubMMRManager()

    def begin_canonical_update(self, fork_height: int, blocks: Any) -> int:
        # No-op for stub manager
        return 0

    def canonical_new_nodes(self, truncation: int) -> list[bytes32]:
        # No-op for stub manager
        return []

    def canonical_state(self, canonical_height: uint32, canonical_header_hash: bytes32) -> MMRState:
        # Stub is never persisted; this is only reachable in tests
        raise NotImplementedError

    def commit_canonical_update(self) -> None:
        # No-op for stub manager
        pass

    def rollback_canonical_update(self) -> None:
        # No-op for stub manager
        pass

    def hydrate(self, nodes: list[bytes32], state: MMRState, blocks: Any) -> None:
        # No-op for stub manager
        pass
