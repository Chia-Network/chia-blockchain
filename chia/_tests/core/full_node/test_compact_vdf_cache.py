from __future__ import annotations

from chia.full_node.compact_vdf_cache import CachedCompactVDF, CompactVDFCache
from chia.types.blockchain_format.vdf import CompressibleVDFField, VDFProof
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8


def _proof(data: bytes = b"proof") -> VDFProof:
    return VDFProof(uint8(0), data, True)


def test_compact_vdf_cache_add_and_get() -> None:
    cache = CompactVDFCache(2)
    header_hash = bytes32(b"\x01" * 32)
    proof = _proof()
    assert cache.add(header_hash, CompressibleVDFField.CC_IP_VDF, uint8(0), proof) is True
    assert cache.has_block(header_hash)
    assert cache.get_proofs(header_hash) == (CachedCompactVDF(CompressibleVDFField.CC_IP_VDF, uint8(0), proof),)
    assert len(cache) == 1


def test_compact_vdf_cache_rejects_when_full() -> None:
    cache = CompactVDFCache(2)
    assert cache.add(bytes32(b"\x01" * 32), CompressibleVDFField.CC_IP_VDF, uint8(0), _proof(b"a")) is True
    assert (
        cache.add(bytes32(b"\x02" * 32), CompressibleVDFField.CC_IP_VDF, uint8(0), _proof(b"b")) is True
    )
    assert cache.is_full()
    assert (
        cache.add(bytes32(b"\x03" * 32), CompressibleVDFField.CC_IP_VDF, uint8(0), _proof(b"c")) is False
    )
    assert len(cache) == 2


def test_compact_vdf_cache_disabled() -> None:
    cache = CompactVDFCache(0)
    assert cache.enabled is False
    assert cache.is_full() is False
    assert cache.add(bytes32(b"\x01" * 32), CompressibleVDFField.CC_IP_VDF, uint8(0), _proof()) is False


def test_compact_vdf_cache_add_multiple_fields_same_block() -> None:
    cache = CompactVDFCache(10)
    header_hash = bytes32(b"\x01" * 32)
    ip_proof = _proof(b"ip")
    sp_proof = _proof(b"sp")
    assert cache.add(header_hash, CompressibleVDFField.CC_IP_VDF, uint8(0), ip_proof) is True
    assert cache.add(header_hash, CompressibleVDFField.CC_SP_VDF, uint8(0), sp_proof) is True
    assert len(cache) == 2
    proofs = {cached.field_vdf: cached.vdf_proof for cached in cache.get_proofs(header_hash)}
    assert proofs[CompressibleVDFField.CC_IP_VDF] == ip_proof
    assert proofs[CompressibleVDFField.CC_SP_VDF] == sp_proof


def test_compact_vdf_cache_add_updates_existing_slot() -> None:
    cache = CompactVDFCache(10)
    header_hash = bytes32(b"\x01" * 32)
    proof1 = _proof(b"one")
    proof2 = _proof(b"two")
    assert cache.add(header_hash, CompressibleVDFField.CC_IP_VDF, uint8(0), proof1) is True
    assert cache.add(header_hash, CompressibleVDFField.CC_IP_VDF, uint8(0), proof2) is True
    assert len(cache) == 1
    assert cache.get_proofs(header_hash)[0].vdf_proof == proof2


def test_compact_vdf_cache_clear() -> None:
    cache = CompactVDFCache(10)
    header_hash = bytes32(b"\x01" * 32)
    assert cache.add(header_hash, CompressibleVDFField.CC_IP_VDF, uint8(0), _proof()) is True
    assert header_hash in cache.modified_header_hashes()
    cache.clear()
    assert len(cache) == 0
    assert cache.modified_header_hashes() == set()


def test_compact_vdf_cache_remove_block() -> None:
    cache = CompactVDFCache(10)
    block1 = bytes32(b"\x01" * 32)
    block2 = bytes32(b"\x02" * 32)
    assert cache.add(block1, CompressibleVDFField.CC_IP_VDF, uint8(0), _proof(b"a")) is True
    assert cache.add(block1, CompressibleVDFField.CC_SP_VDF, uint8(0), _proof(b"b")) is True
    assert cache.add(block2, CompressibleVDFField.CC_IP_VDF, uint8(0), _proof(b"c")) is True
    cache.remove_block(block1)
    assert len(cache) == 1
    assert not cache.has_block(block1)
    assert cache.has_block(block2)
