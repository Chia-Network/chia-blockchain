from __future__ import annotations

from chia.types.blockchain_format.vdf import VDFProof
from chia_rs.sized_bytes import bytes32


class CompactVDFCache:
    """Bounded in-memory cache of compact VDF proofs pending database flush.

    At most one cached compact VDF proof per block header hash.
    """

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._vdf_proof_by_header_hash: dict[bytes32, VDFProof] = {}

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def enabled(self) -> bool:
        return self._capacity > 0

    def is_full(self) -> bool:
        return self.enabled and len(self._vdf_proof_by_header_hash) >= self._capacity

    def __len__(self) -> int:
        return len(self._vdf_proof_by_header_hash)

    def has_block(self, header_hash: bytes32) -> bool:
        return header_hash in self._vdf_proof_by_header_hash

    def get(self, header_hash: bytes32) -> VDFProof | None:
        return self._vdf_proof_by_header_hash.get(header_hash)

    def add(self, header_hash: bytes32, vdf_proof: VDFProof) -> bool:
        if not self.enabled:
            return False
        if header_hash in self._vdf_proof_by_header_hash:
            self._vdf_proof_by_header_hash[header_hash] = vdf_proof
            return True
        if self.is_full():
            return False
        self._vdf_proof_by_header_hash[header_hash] = vdf_proof
        return True

    def modified_header_hashes(self) -> set[bytes32]:
        return set(self._vdf_proof_by_header_hash)

    def remove_block(self, header_hash: bytes32) -> None:
        self._vdf_proof_by_header_hash.pop(header_hash, None)

    def clear(self) -> None:
        self._vdf_proof_by_header_hash.clear()
