"""Bounded in-memory cache of compact VDF proofs pending database flush.

When enabled, accepted compact proofs are stored here instead of being written
to the database immediately. On node shutdown, ``FullNode.flush_compact_vdf_cache``
persists all cached proofs. While the cache is full, new compact proofs are
rejected.

Cache structure
---------------
::

    dict[header_hash → dict[(field_vdf, sub_slot_index) → VDFProof]]

- **Capacity** counts total pending proofs across all blocks, not blocks.
- **Lookup** by ``header_hash`` is O(1); applying cached proofs to a block is
  O(k) where k is the number of proofs cached for that block (typically a
  small constant).

Slot key
--------
Each cached proof is keyed by:

- ``field_vdf`` (``CompressibleVDFField``, 1 byte on the wire): which
  compressible field (CC_EOS, ICC_EOS, CC_SP, CC_IP).
- ``sub_slot_index`` (``uint8``): index into ``finished_sub_slots`` for EOS
  fields; ``0`` for reward-chain fields (CC_SP, CC_IP).

Multiple proofs per block are supported before flush (for example several EOS
sub-slots plus SP and IP on the same block).

What is stored vs. what is already on the block
------------------------------------------------
+----------------------------+----------------------------------+
| Cached                     | Already on the block             |
+============================+==================================+
| ``field_vdf``              | VDF info (challenge, iterations, |
| ``sub_slot_index``         | output) at each slot             |
| compact ``VDFProof``       | full proof being replaced        |
+----------------------------+----------------------------------+

VDF info is not duplicated in the cache. On accept, ``FullNode`` resolves
``sub_slot_index`` from the block's existing VDF info, then patches only the
proof field when serving or flushing.

Replacement and eviction
------------------------
- ``add()`` overwrites an existing ``(header_hash, field_vdf, sub_slot_index)``
  entry without increasing the capacity count. This should not happen in normal
  operation: ``FullNode._can_accept_compact_proof`` rejects duplicate compact
  proofs for a slot before ``add()`` is called. The overwrite exists only so
  ``add()`` is idempotent if the same slot is inserted twice.
- ``remove_block`` drops every cached proof for a block after a successful flush.
- ``CompactVDFCache(0)`` disables caching; proofs are written to the database
  immediately.
"""

from __future__ import annotations

from dataclasses import dataclass

from chia.types.blockchain_format.vdf import CompressibleVDFField, VDFProof
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8


@dataclass(frozen=True)
class CompactVDFProofSlot:
    field_vdf: CompressibleVDFField
    sub_slot_index: uint8


@dataclass(frozen=True)
class CachedCompactVDF:
    field_vdf: CompressibleVDFField
    sub_slot_index: uint8
    vdf_proof: VDFProof


class CompactVDFCache:
    """See module docstring for design and invariants."""

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._proofs_by_block: dict[bytes32, dict[CompactVDFProofSlot, VDFProof]] = {}

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def enabled(self) -> bool:
        return self._capacity > 0

    def is_full(self) -> bool:
        return self.enabled and len(self) >= self._capacity

    def __len__(self) -> int:
        return sum(len(slots) for slots in self._proofs_by_block.values())

    def has_block(self, header_hash: bytes32) -> bool:
        return header_hash in self._proofs_by_block

    def get_proofs(self, header_hash: bytes32) -> tuple[CachedCompactVDF, ...]:
        slots = self._proofs_by_block.get(header_hash)
        if slots is None:
            return ()
        return tuple(
            CachedCompactVDF(slot.field_vdf, slot.sub_slot_index, proof) for slot, proof in slots.items()
        )

    def add(
        self,
        header_hash: bytes32,
        field_vdf: CompressibleVDFField,
        sub_slot_index: uint8,
        vdf_proof: VDFProof,
    ) -> bool:
        if not self.enabled:
            return False
        slot = CompactVDFProofSlot(field_vdf, sub_slot_index)
        block_proofs = self._proofs_by_block.get(header_hash)
        if block_proofs is not None and slot in block_proofs:
            block_proofs[slot] = vdf_proof
            return True
        if self.is_full():
            return False
        if block_proofs is None:
            self._proofs_by_block[header_hash] = {slot: vdf_proof}
        else:
            block_proofs[slot] = vdf_proof
        return True

    def modified_header_hashes(self) -> set[bytes32]:
        return set(self._proofs_by_block)

    def remove_block(self, header_hash: bytes32) -> None:
        self._proofs_by_block.pop(header_hash, None)

    def clear(self) -> None:
        self._proofs_by_block.clear()
