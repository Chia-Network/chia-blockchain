from __future__ import annotations

from dataclasses import dataclass

from chia.types.blockchain_format.vdf import CompressibleVDFField, VDFInfo, VDFProof
from chia_rs.sized_bytes import bytes32


@dataclass(frozen=True)
class CachedCompactVDF:
    vdf_info: VDFInfo
    vdf_proof: VDFProof
    header_hash: bytes32
    field_vdf: CompressibleVDFField


class CompactVDFCache:
    """Bounded in-memory cache of compact VDF proofs pending database flush."""

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._entries: dict[tuple[bytes32, int, bytes], CachedCompactVDF] = {}
        self._modified_blocks: set[bytes32] = set()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def enabled(self) -> bool:
        return self._capacity > 0

    def is_full(self) -> bool:
        return self.enabled and len(self._entries) >= self._capacity

    def __len__(self) -> int:
        return len(self._entries)

    @staticmethod
    def _key(header_hash: bytes32, field_vdf: CompressibleVDFField, vdf_info: VDFInfo) -> tuple[bytes32, int, bytes]:
        return header_hash, int(field_vdf), bytes(vdf_info)

    def contains(self, header_hash: bytes32, field_vdf: CompressibleVDFField, vdf_info: VDFInfo) -> bool:
        return self._key(header_hash, field_vdf, vdf_info) in self._entries

    def get_proof(self, header_hash: bytes32, field_vdf: CompressibleVDFField, vdf_info: VDFInfo) -> VDFProof | None:
        entry = self._entries.get(self._key(header_hash, field_vdf, vdf_info))
        return entry.vdf_proof if entry is not None else None

    def get_entries_for_block(self, header_hash: bytes32) -> list[CachedCompactVDF]:
        return [entry for entry in self._entries.values() if entry.header_hash == header_hash]

    def add(self, entry: CachedCompactVDF) -> bool:
        if not self.enabled:
            return False
        key = self._key(entry.header_hash, entry.field_vdf, entry.vdf_info)
        if key in self._entries:
            return True
        if self.is_full():
            return False
        self._entries[key] = entry
        self._modified_blocks.add(entry.header_hash)
        return True

    def modified_header_hashes(self) -> set[bytes32]:
        return set(self._modified_blocks)

    def remove_block(self, header_hash: bytes32) -> None:
        for entry in self.get_entries_for_block(header_hash):
            self._entries.pop(self._key(entry.header_hash, entry.field_vdf, entry.vdf_info), None)
        self._modified_blocks.discard(header_hash)

    def clear(self) -> None:
        self._entries.clear()
        self._modified_blocks.clear()
