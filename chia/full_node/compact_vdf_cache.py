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
    """Bounded in-memory cache of compact VDF proofs pending database flush.

    Multiple compact VDF proofs may be cached per block, keyed by field and
    sub-slot index (0 for reward-chain fields).
    """

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
