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
        self._by_header_hash: dict[bytes32, dict[tuple[int, bytes], CachedCompactVDF]] = {}
        self._count = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def enabled(self) -> bool:
        return self._capacity > 0

    def is_full(self) -> bool:
        return self.enabled and self._count >= self._capacity

    def __len__(self) -> int:
        return self._count

    @staticmethod
    def _proof_key(field_vdf: CompressibleVDFField, vdf_info: VDFInfo) -> tuple[int, bytes]:
        return int(field_vdf), bytes(vdf_info)

    def has_block(self, header_hash: bytes32) -> bool:
        block_entries = self._by_header_hash.get(header_hash)
        return block_entries is not None and len(block_entries) > 0

    def contains(self, header_hash: bytes32, field_vdf: CompressibleVDFField, vdf_info: VDFInfo) -> bool:
        block_entries = self._by_header_hash.get(header_hash)
        if block_entries is None:
            return False
        return self._proof_key(field_vdf, vdf_info) in block_entries

    def get_proof(
        self, header_hash: bytes32, field_vdf: CompressibleVDFField, vdf_info: VDFInfo
    ) -> VDFProof | None:
        block_entries = self._by_header_hash.get(header_hash)
        if block_entries is None:
            return None
        entry = block_entries.get(self._proof_key(field_vdf, vdf_info))
        return entry.vdf_proof if entry is not None else None

    def get_entries_for_block(self, header_hash: bytes32) -> list[CachedCompactVDF]:
        block_entries = self._by_header_hash.get(header_hash)
        if block_entries is None:
            return []
        return list(block_entries.values())

    def add(self, entry: CachedCompactVDF) -> bool:
        if not self.enabled:
            return False
        proof_key = self._proof_key(entry.field_vdf, entry.vdf_info)
        block_entries = self._by_header_hash.get(entry.header_hash)
        if block_entries is not None and proof_key in block_entries:
            return True
        if self.is_full():
            return False
        if block_entries is None:
            block_entries = {}
            self._by_header_hash[entry.header_hash] = block_entries
        block_entries[proof_key] = entry
        self._count += 1
        return True

    def modified_header_hashes(self) -> set[bytes32]:
        return set(self._by_header_hash)

    def remove_block(self, header_hash: bytes32) -> None:
        block_entries = self._by_header_hash.pop(header_hash, None)
        if block_entries is not None:
            self._count -= len(block_entries)

    def clear(self) -> None:
        self._by_header_hash.clear()
        self._count = 0
