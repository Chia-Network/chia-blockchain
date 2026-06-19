from __future__ import annotations

from chia.full_node.compact_vdf_cache import CachedCompactVDF, CompactVDFCache
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.vdf import CompressibleVDFField, VDFInfo, VDFProof
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64, uint8


def _entry(header_hash: bytes, field_vdf: CompressibleVDFField = CompressibleVDFField.CC_IP_VDF) -> CachedCompactVDF:
    return CachedCompactVDF(
        VDFInfo(bytes32(header_hash), uint64(100), ClassgroupElement.get_default_element()),
        VDFProof(uint8(0), b"proof", True),
        bytes32(header_hash),
        field_vdf,
    )


def test_compact_vdf_cache_add_and_contains() -> None:
    cache = CompactVDFCache(2)
    entry = _entry(b"\x01" * 32)
    assert cache.add(entry) is True
    assert cache.contains(entry.header_hash, entry.field_vdf, entry.vdf_info)
    assert cache.get_proof(entry.header_hash, entry.field_vdf, entry.vdf_info) == entry.vdf_proof
    assert len(cache) == 1


def test_compact_vdf_cache_rejects_when_full() -> None:
    cache = CompactVDFCache(2)
    assert cache.add(_entry(b"\x01" * 32)) is True
    assert cache.add(_entry(b"\x02" * 32)) is True
    assert cache.is_full()
    assert cache.add(_entry(b"\x03" * 32)) is False
    assert len(cache) == 2


def test_compact_vdf_cache_disabled() -> None:
    cache = CompactVDFCache(0)
    assert cache.enabled is False
    assert cache.is_full() is False
    assert cache.add(_entry(b"\x01" * 32)) is False


def test_compact_vdf_cache_clear() -> None:
    cache = CompactVDFCache(10)
    entry = _entry(b"\x01" * 32)
    assert cache.add(entry) is True
    assert entry.header_hash in cache.modified_header_hashes()
    cache.clear()
    assert len(cache) == 0
    assert cache.modified_header_hashes() == set()


def test_compact_vdf_cache_get_entries_for_block() -> None:
    cache = CompactVDFCache(10)
    entry1 = _entry(b"\x01" * 32, CompressibleVDFField.CC_IP_VDF)
    entry2 = _entry(b"\x01" * 32, CompressibleVDFField.CC_SP_VDF)
    entry3 = _entry(b"\x02" * 32, CompressibleVDFField.CC_IP_VDF)
    assert cache.add(entry1) is True
    assert cache.add(entry2) is True
    assert cache.add(entry3) is True
    block1_entries = cache.get_entries_for_block(bytes32(b"\x01" * 32))
    assert len(block1_entries) == 2
    assert entry1 in block1_entries
    assert entry2 in block1_entries
