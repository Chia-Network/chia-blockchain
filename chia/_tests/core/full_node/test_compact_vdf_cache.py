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


def test_compact_vdf_cache_add_and_get() -> None:
    cache = CompactVDFCache(2)
    entry = _entry(b"\x01" * 32)
    assert cache.add(entry) is True
    assert cache.has_block(entry.header_hash)
    assert cache.get(entry.header_hash) == entry
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


def test_compact_vdf_cache_add_updates_existing_header_hash() -> None:
    cache = CompactVDFCache(10)
    header_hash = bytes32(b"\x01" * 32)
    entry1 = _entry(header_hash, CompressibleVDFField.CC_IP_VDF)
    entry2 = _entry(header_hash, CompressibleVDFField.CC_SP_VDF)
    assert cache.add(entry1) is True
    assert cache.add(entry2) is True
    assert len(cache) == 1
    assert cache.get(header_hash) == entry2


def test_compact_vdf_cache_clear() -> None:
    cache = CompactVDFCache(10)
    entry = _entry(b"\x01" * 32)
    assert cache.add(entry) is True
    assert entry.header_hash in cache.modified_header_hashes()
    cache.clear()
    assert len(cache) == 0
    assert cache.modified_header_hashes() == set()


def test_compact_vdf_cache_remove_block() -> None:
    cache = CompactVDFCache(10)
    block1 = bytes32(b"\x01" * 32)
    block2 = bytes32(b"\x02" * 32)
    assert cache.add(_entry(block1, CompressibleVDFField.CC_IP_VDF)) is True
    assert cache.add(_entry(block2, CompressibleVDFField.CC_IP_VDF)) is True
    cache.remove_block(block1)
    assert len(cache) == 1
    assert not cache.has_block(block1)
    assert cache.has_block(block2)
