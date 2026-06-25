from __future__ import annotations

import asyncio
import logging
from typing import Final

import aiohttp
from chia_rs import ConsensusConstants, FullBlock
from chia_rs.sized_ints import uint32

from chia.full_node.compact_vdf_file import (
    COMPACT_VDF_HEIGHT_CHUNK_SIZE,
    CompactVdfEntry,
    apply_compact_proof_to_block,
    compact_vdf_proof,
    find_vdf_info_for_proof,
    needs_compact_proof,
    parse_compact_vdf_entries,
)
from chia.types.blockchain_format.vdf import CompressibleVDFField
from chia.util.priority_thread_pool_executor import Executor

log = logging.getLogger(__name__)

DEFAULT_REMOTE_COMPACT_VDF_BASE_URL: Final = "https://www.xchos.com/compactvdf"

_chunk_cache: dict[tuple[int, int], list[CompactVdfEntry]] = {}
_chunk_locks: dict[tuple[int, int], asyncio.Lock] = {}
_cache_guard = asyncio.Lock()


def chunk_height_range(height: uint32) -> tuple[int, int]:
    start = (int(height) // COMPACT_VDF_HEIGHT_CHUNK_SIZE) * COMPACT_VDF_HEIGHT_CHUNK_SIZE
    end = start + COMPACT_VDF_HEIGHT_CHUNK_SIZE - 1
    return start, end


def remote_compact_vdf_url(base_url: str, height: uint32) -> str:
    start, end = chunk_height_range(height)
    return f"{base_url}-{start}to{end}"


async def _get_chunk_lock(key: tuple[int, int]) -> asyncio.Lock:
    async with _cache_guard:
        lock = _chunk_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _chunk_locks[key] = lock
        return lock


async def _evict_chunks_outside_height(height: uint32) -> None:
    current = chunk_height_range(height)
    async with _cache_guard:
        stale_keys = [key for key in _chunk_cache if key != current]
        for key in stale_keys:
            del _chunk_cache[key]
            _chunk_locks.pop(key, None)
        if len(stale_keys) > 0:
            log.debug(
                "Evicted %s remote compactvdf chunk(s) outside height %s range %sto%s",
                len(stale_keys),
                height,
                current[0],
                current[1],
            )


async def fetch_remote_compact_vdf_entries(base_url: str, height: uint32) -> list[CompactVdfEntry]:
    await _evict_chunks_outside_height(height)
    start, end = chunk_height_range(height)
    key = (start, end)
    cached = _chunk_cache.get(key)
    if cached is not None:
        return cached

    lock = await _get_chunk_lock(key)
    async with lock:
        cached = _chunk_cache.get(key)
        if cached is not None:
            return cached

        url = remote_compact_vdf_url(base_url, height)
        entries: list[CompactVdfEntry] = []
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session, session.get(url) as response:
                if response.status == 404:
                    log.debug("Remote compactvdf file not found: %s", url)
                elif response.status != 200:
                    log.warning("Failed to fetch remote compactvdf file %s: HTTP %s", url, response.status)
                else:
                    text = await response.text()
                    entries = parse_compact_vdf_entries(text)
                    log.debug("Loaded %s remote compactvdf entries from %s", len(entries), url)
        except Exception:
            log.warning("Failed to fetch remote compactvdf file %s", url, exc_info=True)

        _chunk_cache[key] = entries
        return entries


async def apply_compact_vdf_entries(
    constants: ConsensusConstants,
    block: FullBlock,
    entries: list[CompactVdfEntry] | None,
    pool: Executor | None = None,
) -> FullBlock:
    if entries is None or len(entries) == 0:
        return block

    header_hash = block.header_hash
    block_entries = [entry for entry in entries if entry.header_hash == header_hash]
    if len(block_entries) == 0:
        return block

    applied = 0
    for entry in block_entries:
        field_vdf = CompressibleVDFField(int(entry.field_vdf))
        vdf_proof = compact_vdf_proof(entry.witness)
        if pool is not None:
            vdf_info = await pool.run_in_loop(find_vdf_info_for_proof, block, field_vdf, vdf_proof, constants)
        else:
            vdf_info = find_vdf_info_for_proof(block, field_vdf, vdf_proof, constants)
        if vdf_info is None:
            log.debug(
                "Remote compact VDF proof did not validate for block %s height %s field_vdf %s",
                header_hash,
                block.height,
                field_vdf,
            )
            continue
        if not needs_compact_proof(vdf_info, block, field_vdf):
            continue
        new_block = apply_compact_proof_to_block(block, vdf_info, vdf_proof, field_vdf)
        if new_block is None:
            log.warning(
                "Could not apply remote compact VDF proof for block %s height %s field_vdf %s",
                header_hash,
                block.height,
                field_vdf,
            )
            continue
        block = new_block
        applied += 1

    if applied > 0:
        log.info(
            "Applied %s remote compact VDF proof(s) to block %s height %s before validation",
            applied,
            header_hash,
            block.height,
        )
    return block


async def apply_remote_compact_vdfs(
    constants: ConsensusConstants,
    block: FullBlock,
    base_url: str | None,
    pool: Executor | None = None,
) -> FullBlock:
    if base_url is None or base_url == "":
        return block

    entries = await fetch_remote_compact_vdf_entries(base_url, block.height)
    return await apply_compact_vdf_entries(constants, block, entries, pool)
